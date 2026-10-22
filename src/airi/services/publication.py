"""Reanudación acotada de respuestas confirmadas y no publicadas."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from airi.domain.turns import TurnRecord
from airi.services.turn_journal import TurnJournal

log = logging.getLogger(__name__)

Publisher = Callable[[TurnRecord], Awaitable[None]]


class PublicationResumer:
    """Publica pendientes dentro de la vigencia y las marca como enviadas."""

    def __init__(
        self,
        journal: TurnJournal,
        *,
        ttl: float,
        clock: Callable[[], float] = time.time,
    ):
        self.journal = journal
        self.ttl = float(ttl)
        self.clock = clock

    async def resume(self, publisher: Publisher) -> int:
        now = float(self.clock())
        published = 0
        for record in self.journal.pending_publications(now=now, ttl=self.ttl):
            try:
                await publisher(record)
            except Exception:
                log.exception(
                    "No se pudo republicar el turno %s; queda pendiente",
                    record.turn_key,
                )
                continue
            try:
                self.journal.mark_published(record.turn_key, now=float(self.clock()))
            except Exception:
                log.exception(
                    "Se publicó el turno %s pero no se pudo marcar como publicado",
                    record.turn_key,
                )
                continue
            published += 1
        return published
