"""Contrato de turnos: clave, estados y serialización (dominio puro)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable

TURN_NAMESPACE = "airi.turn.v1"


class TurnStatus(str, Enum):
    """Estado durable de un turno."""

    PROCESSING = "processing"
    COMMITTED = "committed"
    PUBLISHED = "published"
    FAILED = "failed"


class TransitionError(ValueError):
    """Transición de estado de turno no permitida."""


#: Transiciones válidas: desde un estado, hacia qué estados se puede avanzar.
_ALLOWED = {
    TurnStatus.PROCESSING: {TurnStatus.COMMITTED, TurnStatus.FAILED},
    TurnStatus.COMMITTED: {TurnStatus.PUBLISHED, TurnStatus.FAILED},
    TurnStatus.PUBLISHED: set(),
    TurnStatus.FAILED: set(),
}


def can_transition(current: TurnStatus, new: TurnStatus) -> bool:
    """True si el turno puede pasar de `current` a `new`."""
    return new in _ALLOWED.get(current, set())


def transition(current: TurnStatus, new: TurnStatus) -> TurnStatus:
    """Valida y devuelve el nuevo estado."""
    if not can_transition(current, new):
        raise TransitionError(f"transición no permitida: {current.value} -> {new.value}")
    return new


def make_turn_key(channel_id: object, message_ids: Iterable[object]) -> str:
    """Clave determinista del lote: canal + primer mensaje."""
    ids = [str(message_id) for message_id in message_ids if str(message_id)]
    if not ids:
        raise ValueError("un turno necesita al menos un message_id")
    return f"{channel_id}:{ids[0]}"


def hash_text(text: str) -> str:
    """Huella estable del texto publicable."""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TurnRecord:
    """Registro durable de un turno."""

    turn_key: str
    channel_id: str
    message_ids: tuple[str, ...]
    status: TurnStatus
    reply_text: str
    created_at: float
    updated_at: float
    published_at: float | None = None
    failure_reason: str = ""
    reply_hash: str = ""

    def with_status(
        self,
        new: TurnStatus,
        *,
        now: float,
        published_at: float | None = None,
        failure_reason: str | None = None,
        reply_text: str | None = None,
    ) -> "TurnRecord":
        """Devuelve una copia con la transición validada."""
        transition(self.status, new)
        text = self.reply_text if reply_text is None else str(reply_text)
        return replace(
            self,
            status=new,
            updated_at=float(now),
            published_at=published_at if published_at is not None else self.published_at,
            failure_reason=(
                self.failure_reason if failure_reason is None else str(failure_reason)
            ),
            reply_text=text,
            reply_hash=hash_text(text) if text else "",
        )

    def with_reply(self, text: str, *, now: float) -> "TurnRecord":
        """Actualiza el texto publicable sin cambiar de estado."""
        return replace(
            self,
            reply_text=str(text),
            reply_hash=hash_text(text) if text else "",
            updated_at=float(now),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_key": self.turn_key,
            "channel_id": self.channel_id,
            "message_ids": list(self.message_ids),
            "status": self.status.value,
            "reply_text": self.reply_text,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "published_at": self.published_at,
            "failure_reason": self.failure_reason,
            "reply_hash": self.reply_hash,
        }

    @classmethod
    def from_dict(cls, data: object) -> "TurnRecord":
        if not isinstance(data, dict):
            raise ValueError("registro de turno inválido")
        try:
            status = TurnStatus(str(data["status"]))
        except (KeyError, ValueError) as exc:
            raise ValueError("estado de turno inválido") from exc
        raw_ids = data.get("message_ids") or []
        if not isinstance(raw_ids, list):
            raise ValueError("message_ids inválido")
        return cls(
            turn_key=str(data.get("turn_key", "")),
            channel_id=str(data.get("channel_id", "")),
            message_ids=tuple(str(value) for value in raw_ids),
            status=status,
            reply_text=str(data.get("reply_text", "")),
            created_at=float(data.get("created_at", 0.0) or 0.0),
            updated_at=float(data.get("updated_at", 0.0) or 0.0),
            published_at=_optional_float(data.get("published_at")),
            failure_reason=str(data.get("failure_reason", "")),
            reply_hash=str(data.get("reply_hash", "")),
        )


def new_turn_record(
    *,
    turn_key: str,
    channel_id: object,
    message_ids: Iterable[object],
    status: TurnStatus = TurnStatus.PROCESSING,
    reply_text: str = "",
    now: float,
) -> TurnRecord:
    """Crea un registro nuevo."""
    ids = tuple(str(message_id) for message_id in message_ids)
    if not ids:
        raise ValueError("un turno necesita al menos un message_id")
    text = str(reply_text)
    return TurnRecord(
        turn_key=str(turn_key),
        channel_id=str(channel_id),
        message_ids=ids,
        status=status,
        reply_text=text,
        created_at=float(now),
        updated_at=float(now),
        reply_hash=hash_text(text) if text else "",
    )


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "TURN_NAMESPACE",
    "TransitionError",
    "TurnRecord",
    "TurnStatus",
    "can_transition",
    "hash_text",
    "make_turn_key",
    "new_turn_record",
    "transition",
]
