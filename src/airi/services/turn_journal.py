"""Registro durable de turnos en el agregado del servidor."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from airi.domain.turns import TurnRecord, TurnStatus, make_turn_key, new_turn_record
from airi.services.persistence import SaveKind, StatePersistence
from airi.services.state import AppState


class ClaimStatus(str, Enum):
    CLAIMED = "claimed"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class ClaimResult:
    status: ClaimStatus
    turn_key: str
    record: TurnRecord | None = None


class TurnJournal:
    """Gestiona reclamaciones y estados de turno dentro de `AppState`."""

    def __init__(
        self,
        state: AppState,
        *,
        persistence: StatePersistence | None = None,
    ):
        self.state = state
        self.persistence = persistence

    # ------------------------------------------------------------------
    # Reclamación
    # ------------------------------------------------------------------

    def claim(
        self, channel_id: object, message_ids: Iterable[object], *, now: float
    ) -> ClaimResult:
        channel = str(channel_id)
        ids = [str(message_id) for message_id in message_ids]
        if not ids:
            raise ValueError("un turno necesita al menos un message_id")
        turn_key = make_turn_key(channel, ids)
        indexes = [f"{channel}:{message_id}" for message_id in ids]
        for index in indexes:
            if index in self.state.message_index:
                return ClaimResult(ClaimStatus.DUPLICATE, turn_key)
        if turn_key in self.state.turn_records:
            return ClaimResult(ClaimStatus.DUPLICATE, turn_key)

        record = new_turn_record(
            turn_key=turn_key,
            channel_id=channel,
            message_ids=ids,
            status=TurnStatus.PROCESSING,
            now=now,
        )
        self.state.turn_records[turn_key] = record.to_dict()
        for index in indexes:
            self.state.message_index[index] = turn_key
        self._persist()
        return ClaimResult(ClaimStatus.CLAIMED, turn_key, record)

    # ------------------------------------------------------------------
    # Transiciones
    # ------------------------------------------------------------------

    def mark_committed(self, turn_key: str, reply_text: str, *, now: float):
        return self._transition(
            turn_key,
            TurnStatus.COMMITTED,
            now=now,
            reply_text=reply_text,
        )

    def mark_published(self, turn_key: str, *, now: float):
        return self._transition(
            turn_key,
            TurnStatus.PUBLISHED,
            now=now,
            published_at=now,
        )

    def mark_failed(self, turn_key: str, reason: str, *, now: float):
        return self._transition(
            turn_key,
            TurnStatus.FAILED,
            now=now,
            failure_reason=reason,
        )

    # ------------------------------------------------------------------
    # Consultas y mantenimiento
    # ------------------------------------------------------------------

    def get(self, turn_key: str) -> TurnRecord | None:
        data = self.state.turn_records.get(str(turn_key))
        if not isinstance(data, dict):
            return None
        try:
            return TurnRecord.from_dict(data)
        except ValueError:
            return None

    def pending_publications(
        self, *, now: float, ttl: float
    ) -> tuple[TurnRecord, ...]:
        pending = []
        for turn_key, data in self.state.turn_records.items():
            record = self._record(turn_key, data)
            if record is None or record.status is not TurnStatus.COMMITTED:
                continue
            if float(now) - record.updated_at <= float(ttl):
                pending.append(record)
        pending.sort(key=lambda record: (record.created_at, record.turn_key))
        return tuple(pending)

    def abandon_stale_processing(self, *, now: float, ttl: float) -> int:
        changed = 0
        for turn_key, data in list(self.state.turn_records.items()):
            record = self._record(turn_key, data)
            if record is None or record.status is not TurnStatus.PROCESSING:
                continue
            if float(now) - record.updated_at <= float(ttl):
                continue
            updated = record.with_status(
                TurnStatus.FAILED,
                now=now,
                failure_reason="proceso interrumpido o abandonado",
            )
            self.state.turn_records[turn_key] = updated.to_dict()
            changed += 1
        if changed:
            self._persist()
        return changed

    def prune(self, *, now: float, retain_seconds: float) -> int:
        removed: set[str] = set()
        for turn_key, data in list(self.state.turn_records.items()):
            record = self._record(turn_key, data)
            if record is None:
                removed.add(turn_key)
                continue
            if record.status not in (TurnStatus.PUBLISHED, TurnStatus.FAILED):
                continue
            if float(now) - record.updated_at > float(retain_seconds):
                removed.add(turn_key)
        for turn_key in removed:
            self.state.turn_records.pop(turn_key, None)
        if removed:
            for index, turn_key in list(self.state.message_index.items()):
                if turn_key in removed:
                    self.state.message_index.pop(index, None)
            self._persist()
        return len(removed)

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _transition(
        self,
        turn_key: str,
        status: TurnStatus,
        *,
        now: float,
        published_at: float | None = None,
        failure_reason: str | None = None,
        reply_text: str | None = None,
    ) -> TurnRecord | None:
        record = self.get(turn_key)
        if record is None:
            return None
        updated = record.with_status(
            status,
            now=now,
            published_at=published_at,
            failure_reason=failure_reason,
            reply_text=reply_text,
        )
        self.state.turn_records[str(turn_key)] = updated.to_dict()
        self._persist()
        return updated

    @staticmethod
    def _record(turn_key: str, data: object) -> TurnRecord | None:
        if not isinstance(data, dict):
            return None
        try:
            record = TurnRecord.from_dict(data)
        except ValueError:
            return None
        return record if record.turn_key == str(turn_key) else record

    def _persist(self) -> None:
        if self.persistence is not None:
            self.persistence.save(kind=SaveKind.METADATA)
