"""Orquesta un turno: reclamar, generar, validar, confirmar y publicar."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from airi.domain.turn_guard import GuardDecision, validate_turn
from airi.services.conversation import ConversationService, TurnContext, TurnResult
from airi.services.persistence import StatePersistence
from airi.services.turn_journal import TurnJournal

log = logging.getLogger(__name__)


class StaleTurnError(RuntimeError):
    """El borrador ya no se puede aplicar porque cambió el estado."""

    def __init__(self, decision: GuardDecision):
        super().__init__(f"turno obsoleto: {decision.value}")
        self.decision = decision


@dataclass(frozen=True)
class CommittedTurn:
    turn_key: str
    result: TurnResult


Publisher = Callable[[CommittedTurn], Awaitable[None]]


class TurnCoordinator:
    def __init__(
        self,
        *,
        service: ConversationService,
        journal: TurnJournal,
        persistence: StatePersistence,
        commit_lock: asyncio.Lock | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.service = service
        self.journal = journal
        self.persistence = persistence
        self.commit_lock = commit_lock or asyncio.Lock()
        self.clock = clock

    async def execute(
        self,
        *,
        channel_id: object,
        user: object,
        messages: Sequence,
        message_ids: Sequence[object],
        context: TurnContext,
        publisher: Publisher,
    ) -> TurnResult | None:
        now = float(self.clock())
        claim = self.journal.claim(channel_id, message_ids, now=now)
        if claim.status.value == "duplicate":
            log.info("Turno duplicado ignorado: %s", claim.turn_key)
            return None
        turn_key = claim.turn_key
        # La referencia estable del diario pasa al contexto de generación para
        # que el modelo pueda citar el turno actual como evidencia.
        context.turn_key = turn_key

        try:
            draft = await self.service.generate_turn(user, messages, context)
        except Exception as exc:
            self._mark_failed(turn_key, f"generación fallida: {type(exc).__name__}")
            raise

        state = self.service.state
        decision = validate_turn(
            draft_season=draft.season,
            draft_date=draft.date_fingerprint,
            current_season=int(state.world.get("season", 1) or 1),
            current_date=state.dates.get(str(getattr(user, "id", ""))),
            draft_relationship=draft.relationship_fingerprint,
            current_relationship=self.service.relationships.fingerprint(
                getattr(user, "id", "")
            ),
        )
        if decision is not GuardDecision.VALID:
            self._mark_failed(turn_key, decision.value)
            raise StaleTurnError(decision)

        async with self.commit_lock:
            try:
                with self.persistence.transaction():
                    result = self.service.apply_turn(draft)
                    if result.skipped:
                        self.journal.mark_failed(
                            turn_key, "respuesta omitida", now=float(self.clock())
                        )
                    else:
                        self.journal.mark_committed(
                            turn_key, result.reply or "", now=float(self.clock())
                        )
            except Exception as exc:
                self._mark_failed(
                    turn_key, f"commit fallido: {type(exc).__name__}"
                )
                raise
            try:
                await self.service.finish_trace(context, result.trace)
            except Exception:
                log.exception("No se pudo guardar la traza del turno")

        if result.skipped:
            return result

        committed = CommittedTurn(turn_key=turn_key, result=result)
        try:
            await publisher(committed)
        except Exception:
            # El registro queda committed para reintentar al arrancar.
            log.exception("Publicación fallida; el turno queda pendiente")
            raise

        try:
            self.journal.mark_published(turn_key, now=float(self.clock()))
        except Exception:
            log.exception("No se pudo marcar el turno como publicado")
        return result

    def _mark_failed(self, turn_key: str, reason: str) -> None:
        try:
            self.journal.mark_failed(turn_key, reason, now=float(self.clock()))
        except Exception:
            log.exception("No se pudo marcar el turno %s como fallido", turn_key)
