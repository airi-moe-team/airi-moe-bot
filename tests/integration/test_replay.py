"""Regresión del replay: fixtures de trazas y paso de cita fiel."""

from __future__ import annotations

import asyncio
import os

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


def test_replay_active_turn_preserves_session_schema_and_stay_active(tmp_path):
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("Sigo en la conversación.", stay_active=True)])
    svc = ConversationService(llm=llm, state=state, clock=lambda: NOW)
    generated = run(svc.run_turn(
        DAVID,
        [(DAVID, "¿Sigues por aquí?")],
        TurnContext(conversation_mode="active", now=NOW),
    ))
    # The persisted event's kind is the runtime session kind, independent of
    # the internal user-message trigger used to construct this fixture.
    generated.trace.kind = "active"
    path = save_turn_trace(generated.trace, str(tmp_path))

    replayed = run(replay_trace(path))

    assert generated.trace.kind == "active"
    assert replayed.conversation_mode == "active"
    assert replayed.stay_active is True
    assert replayed.checks["session_schema"] is True
    assert replayed.checks["stay_active"] is True
    assert replayed.matches_original


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
