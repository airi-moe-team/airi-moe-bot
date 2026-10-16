"""Servicio de fecha: máquina de estados + avisos + cierre (orquestación)."""

from __future__ import annotations

import logging
import random

from airi.domain.constants import DATE_QUESTION_DELTA_MAX, DATE_SUMMARY_MAX_TOKENS
from airi.domain.dates import (
    last_chance_recovery,
    question_failed_hard,
    question_option,
    roll_question,
    step_date,
)
from airi.domain.prompts import date_summary_prompt
from airi.domain.text_filters import clean_summary
from airi.domain.texts import (
    DATE_CRISIS_TEXT,
    DATE_QUESTION_FALLBACK,
    date_final_text,
    end_keyword_hit,
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
    if event == "timeout":
        return (
            f"La cita con {name} ({scene}) se quedó a medias: se me fue el tiempo "
            "y no pudimos terminarla. Me he quedado con las ganas."
        )
    return (
        f"He tenido una cita con {name} ({scene}). Ha sido un momento muy bonito."
    )


class DateService:
    """Avanza y cierra citas; notifica vía el Notifier (no conoce Discord)."""

    def __init__(self, *, state: AppState, notifier=None, clock=None, rng=None,
                 llm_chat=None):
        self.state = state
        self.notifier = notifier
        self.clock = clock
        # RNG inyectable para tests deterministas del turno de la pregunta.
        self.rng = rng if rng is not None else random.Random()
        # Callable async opcional para pedir el resumen de la cita al LLM.
        # Firma: `await llm_chat(messages, *, max_tokens=None) -> str`.
        self.llm_chat = llm_chat

    def _now(self, now):
        if now is not None:
            return now
        if self.clock is not None:
            return self.clock()
        import time as _time

        return _time.time()

    async def process_turn(
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
        allow_crisis_drop=True,
    ):
        """Avanza un turno de la cita, comunica el resultado y cierra si toca.

        Devuelve el evento del turno (ver airi.domain.dates.step_date).
        """
        now = self._now(now)
        uid = str(user.id)
        end_keyword = end_keyword_hit(text)
        new_state, event = step_date(
            session,
            delta=delta,
            points=points,
            decision=date_decision,
            reason=date_reason,
            last_chance_result=last_chance_result,
            end_keyword=bool(end_keyword),
            now=now,
            question=question,
            fallback_question=DATE_QUESTION_FALLBACK,
            allow_crisis_drop=allow_crisis_drop,
        )
        # Motivo del cierre y salud de la pregunta, para la traza y el diario.
        session["end_keyword"] = end_keyword
        if date_decision == "question" and event != "question":
            session["question_invalid"] = True
            log.warning(
                "Cita de %s: date_decision=question sin pregunta válida "
                "(payload=%r); se ignora",
                uid,
                question,
            )
        elif event == "question":
            session["question_invalid"] = False
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

        if event == "crisis":
            if self.notifier is not None:
                await self.notifier.send(DATE_CRISIS_TEXT)
            self.state.save_dates()
            return event

        if event in ("continue", "question"):
            self.state.save_dates()
            return event

        # Eventos que cierran la cita: recovered / partial_recovery /
        # failed_last_chance / ending.
        if self.notifier is not None:
            await self.notifier.send(date_final_text(event))
        # Resumen de lo vivido (si hay LLM) antes de cerrar: `finish_date` lo
        # usa como texto del diario y cae al genérico si no existe.
        await self.finalize_date_summary(user.id, session, event, now=now)
        self.finish_date(user.id, session, event, now=now)
        return event

    # ------------------------------------------------------------------
    # Pregunta decisiva
    # ------------------------------------------------------------------

    def resolve_question(self, session, index):
        """Tira el dado de la alternativa `index`. Devuelve el resultado o None.

        El resultado es un dict con `index`, `label`, `action`, `win`, `delta`
        y `hard_fail` (fallo grave: entra en última oportunidad).
        """
        option = question_option(session, index)
        if option is None:
            return None
        win, delta = roll_question(option, self.rng)
        return {
            "index": int(index),
            "label": option.get("label", ""),
            "action": option.get("action", ""),
            "win": bool(win),
            "delta": int(delta),
            "hard_fail": (not win) and question_failed_hard(delta),
        }

    def apply_question_result(self, session, result, *, user_id, now=None):
        """Aplica el swing ya resuelto y deja la sesión para el turno de reacción.

        Marca `force_crisis` si el fallo es grave para que el turno de reacción
        (con `allow_crisis_drop=False`) entre en última oportunidad. Devuelve el
        delta realmente aplicado.
        """
        now = self._now(now)
        delta = int(result.get("delta", 0) or 0)
        applied = 0
        if delta:
            applied = self.state.apply_affinity(
                user_id,
                delta,
                now=now,
                delta_max=DATE_QUESTION_DELTA_MAX,
                delta_min=-DATE_QUESTION_DELTA_MAX,
            )
        session["question_pending"] = False
        session["question_result"] = {
            "index": int(result.get("index", -1)),
            "win": bool(result.get("win")),
            "delta": delta,
            "label": str(result.get("label", "")),
        }
        if result.get("hard_fail"):
            session["force_crisis"] = True
        self.state.save_dates()
        log.info(
            "Pregunta de %s resuelta: %s delta=%+d (aplicado %+d)",
            user_id, "acierto" if result.get("win") else "fallo", delta, applied,
        )
        return applied

    def finish_date(self, user_id, session, event, *, now):
        """Cierra la cita: registra el resultado en el diario y la elimina."""
        uid = str(user_id)
        name = self.state.display_name(uid)
        scene = session.get("scene", "")
        # Si el resumen del LLM quedó en la sesión, mandan sus palabras; si no
        # (sin LLM o fallo), se usa el texto genérico determinista.
        text = session.get("summary") or _finish_diary_text(event, name, scene)
        self.state.log_diary_event("date", user_id, text)
        session["state"] = "closed"
        self.state.dates.pop(uid, None)
        self.state.save_dates()
        log.info("Cita de %s finalizada (evento=%s)", uid, event)

    async def finalize_date_summary(self, user_id, session, event, *, now=None):
        """Genera el resumen de la cita desde el historial privado y lo guarda.

        Deja el texto en `session["summary"]` para que `finish_date` lo use como
        entrada del diario. Si no hay LLM inyectado o falla la llamada, no toca
        la sesión (se conservará el texto genérico de cierre).
        """
        if self.llm_chat is None:
            return None
        history = session.get("history") or []
        prompt = date_summary_prompt(session, event, history)
        try:
            raw = await self.llm_chat(
                [{"role": "user", "content": prompt}],
                max_tokens=DATE_SUMMARY_MAX_TOKENS,
            )
        except Exception:
            log.exception("No se pudo resumir la cita de %s", user_id)
            return None
        text = clean_summary(raw)
        if not text:
            return None
        session["summary"] = text
        log.info("Resumen de la cita de %s guardado para el diario", user_id)
        return text
