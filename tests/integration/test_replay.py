"""Regresión del replay: fixtures de trazas y paso de cita fiel."""

from __future__ import annotations

import asyncio
import os

from airi.domain.constants import DATE_MAX_TURNS, DATE_QUESTION_GRACE_TURNS
from airi.domain.dates import new_date_session
from airi.observability.replay import replay_trace
from airi.observability.trace import save_turn_trace
from airi.services.conversation import ConversationService, TurnContext
from airi.services.date_service import DateService
from airi.testing import FakeLLM, FakeNotifier, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")
FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "traces", "affinity_delta_without_reason.json"
)


def run(coro):
    return asyncio.run(coro)


def test_affinity_delta_without_reason_fixture_replays():
    result = run(replay_trace(FIXTURE))
    assert result.reproducible
    assert result.matches_original, result.checks
    # delta 3 sin motivo (affinity_event="none") no debe aplicarse.
    assert result.affinity_delta_applied == 0


def _golden_date_trace(tmp_path, *, capture_date_event):
    """Genera una traza de cita; opcionalmente captura el paso de DateService."""
    session = new_date_session("una cena a la luz de las velas", 10, now=NOW)
    state, _ = make_state(dates={"42": session})
    llm = FakeLLM(replies=[
        llm_json("qué bien", affinity_delta=2, affinity_event="cena")
    ])
    svc = ConversationService(
        llm=llm, state=state, notifier=FakeNotifier(), clock=lambda: NOW,
        date_delta_max=8,
    )
    result = run(svc.run_turn(
        DAVID, [(DAVID, "qué rica la cena")], TurnContext()
    ))

    if capture_date_event:
        date_svc = DateService(state=state, notifier=None, clock=lambda: NOW)
        result.trace.date_event = run(date_svc.process_turn(
            state.dates["42"],
            user=DAVID,
            text="qué rica la cena",
            delta=result.affinity_delta,
            points=state.entry_points(DAVID.id),
            date_decision=result.date_decision,
            date_reason=result.date_reason,
            last_chance_result=result.last_chance_result,
            now=NOW,
        ))

    return save_turn_trace(result.trace, str(tmp_path))


def test_replay_date_turn_verifies_date_event(tmp_path):
    path = _golden_date_trace(tmp_path, capture_date_event=True)
    result = run(replay_trace(path))

    assert result.matches_original, result.checks
    assert result.checks["date_event"] is True
    assert result.date_event == "continue"


def test_replay_date_turn_without_date_event_is_tolerated(tmp_path):
    path = _golden_date_trace(tmp_path, capture_date_event=False)
    result = run(replay_trace(path))

    assert "date_event" not in result.checks
    assert result.matches_original, result.checks


def _golden_forced_question_trace(tmp_path):
    """Traza del último turno de la gracia: la reserva fuerza el evento `question`.

    La sesión llega al tope de turnos sin que el modelo haya propuesto la
    pregunta decisiva (`decision="continue"`). Sin el forzado el turno cerraría
    con `ending`; la reserva determinista garantiza que el evento `question`
    siempre ocurra. El replay debe reproducir ese evento desde el snapshot.
    """
    session = new_date_session("una merienda en el parque", 0, now=NOW)
    session["turns"] = DATE_MAX_TURNS + DATE_QUESTION_GRACE_TURNS - 1
    state, _ = make_state(dates={"42": session})
    llm = FakeLLM(replies=[llm_json("qué bien lo pasamos")])
    svc = ConversationService(
        llm=llm, state=state, notifier=FakeNotifier(), clock=lambda: NOW,
        date_delta_max=8,
    )
    result = run(svc.run_turn(DAVID, [(DAVID, "qué bien lo pasamos")], TurnContext()))

    date_svc = DateService(state=state, notifier=None, clock=lambda: NOW)
    result.trace.date_event = run(date_svc.process_turn(
        state.dates["42"],
        user=DAVID,
        text="qué bien lo pasamos",
        delta=result.affinity_delta,
        points=state.entry_points(DAVID.id),
        date_decision=result.date_decision,
        date_reason=result.date_reason,
        last_chance_result=result.last_chance_result,
        now=NOW,
    ))
    return save_turn_trace(result.trace, str(tmp_path))


def test_replay_date_turn_forced_question(tmp_path):
    path = _golden_forced_question_trace(tmp_path)
    result = run(replay_trace(path))

    assert result.matches_original, result.checks
    assert result.checks["date_event"] is True
    assert result.date_event == "question"
