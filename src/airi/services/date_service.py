"""Servicio de fecha: máquina de estados + avisos + cierre (orquestación)."""

from __future__ import annotations

import logging

from airi.domain.dates import last_chance_recovery, step_date
from airi.domain.texts import (
    DATE_CRISIS_TEXT,
    DATE_END_KEYWORDS,
    date_final_text,
)
from airi.services.state import AppState

log = logging.getLogger(__name__)


# Textos de cierre del diario según el desenlace de la cita.
def _finish_diary_text(event, name, scene):
    if event == "recovered":
        return (
            f"Casi arruino la cita con {name} ({scene}), pero me demostró que le "
            "importo y la salvamos juntos. Hoy me he enamorado un poquito más."
        )
    if event == "partial_recovery":
        return (
            f"La cita con {name} ({scene}) estuvo a punto de romperse. Lo intentó, "
            "pero me quedé con dudas... Quizá merezca otra oportunidad."
        )
    if event == "failed_last_chance":
        return (
            f"Hoy la cita con {name} ({scene}) salió mal y no consiguió "
            "reconducirla. Me he quedado con el corazón encogido."
        )
    return (
        f"He tenido una cita con {name} ({scene}). Ha sido un momento muy bonito."
    )


class DateService:
    """Avanza y cierra citas; los avisos se pueden diferir al commit."""

    def __init__(self, *, state: AppState, notifier=None, clock=None):
        self.state = state
        self.notifier = notifier
        self.clock = clock

    def _now(self, now):
        if now is not None:
            return now
        if self.clock is not None:
            return self.clock()
        import time as _time

        return _time.time()

    def advance(
        self,
        session,
        *,
        user,
        text,
        delta,
        points,
        date_decision,
        date_reason,
        last_chance_result,
        now=None,
        question=None,
    ):
        """Avanza la cita sin enviar avisos. Devuelve `(evento, avisos)`."""
        now = self._now(now)
        uid = str(user.id)
        end_keyword = any(kw in text.lower() for kw in DATE_END_KEYWORDS)
        new_state, event = step_date(
            session,
            delta=delta,
            points=points,
            decision=date_decision,
            reason=date_reason,
            last_chance_result=last_chance_result,
            end_keyword=end_keyword,
            now=now,
            question=question,
        )
        log.info(
            "Cita de %s: turno %s → estado %s (evento=%s)",
            uid, session.get("turns"), new_state, event,
        )

        # La última oportunidad puede devolver parte de la afinidad perdida.
        if event in ("recovered", "partial_recovery"):
            result = session.get("last_chance_result", "none")
            recovered = last_chance_recovery(session, result, points)
            if recovered:
                self.state.apply_affinity(user.id, recovered, now=now)
                log.info("La cita con %s se reconduce: +%d de afinidad", uid, recovered)

        notices = []
        if event == "crisis":
            self.state.save_dates()
            notices.append(DATE_CRISIS_TEXT)
            return event, notices

        if event == "continue":
            self.state.save_dates()
            return event, notices

        # La pregunta decisiva: la cita sigue abierta, solo se publica la
        # pregunta con sus botones.
        if event == "question":
            self.state.save_dates()
            return event, notices

        # Eventos que cierran la cita: recovered / partial_recovery /
        # failed_last_chance / ending.
        self.finish_date(user.id, session, event, now=now)
        notices.append(date_final_text(event))
        return event, notices

    async def process_turn(self, *args, **kwargs):
        """Compatibilidad: avanza y envía los avisos inmediatamente."""
        event, notices = self.advance(*args, **kwargs)
        if self.notifier is not None:
            for notice in notices:
                await self.notifier.send(notice)
        return event

    def process_turn_deferred(self, *args, **kwargs):
        """Avanza y devuelve los avisos para publicarlos tras el commit."""
        return self.advance(*args, **kwargs)

    def finish_date(self, user_id, session, event, *, now):
        """Cierra la cita: registra el resultado en el diario y la elimina."""
        uid = str(user_id)
        name = self.state.display_name(uid)
        scene = session.get("scene", "")
        self.state.log_diary_event(
            "date", user_id, _finish_diary_text(event, name, scene)
        )
        session["state"] = "closed"
        self.state.dates.pop(uid, None)
        self.state.save_dates()
        log.info("Cita de %s finalizada (evento=%s)", uid, event)
