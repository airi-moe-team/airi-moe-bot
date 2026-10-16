"""1.4: un `date_decision=question` sin pregunta válida se registra, no se traga."""

import asyncio

from airi.domain.dates import new_date_session
from airi.services.date_service import DateService
from airi.testing import FakeNotifier, FakeUser, make_state

NOW = 1_000_000.0
ANA = FakeUser(1, "Ana")

VALID_QUESTION = {
    "text": "¿Qué te gusta de mí?",
    "options": [
        {"label": "todo", "action": "sonríe", "up_chance": 0.8,
         "delta_up": 12, "delta_down": -6},
    ],
}


def _service(state):
    return DateService(state=state, notifier=FakeNotifier(), clock=lambda: NOW)


def _run(service, session, **kw):
    defaults = dict(
        user=ANA, text="hola", delta=0, points=40,
        date_decision="continue", date_reason="none",
        last_chance_result="none", now=NOW,
    )
    defaults.update(kw)
    return asyncio.run(service.process_turn(session, **defaults))


def test_question_without_payload_is_marked_invalid():
    state, _ = make_state()
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = 2
    state.dates["1"] = session

    event = _run(
        _service(state), session, date_decision="question", question=None
    )

    assert event == "continue"
    assert session["question_invalid"] is True
    assert session["question_used"] is False


def test_valid_question_clears_invalid_flag():
    state, _ = make_state()
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = 2
    session["question_invalid"] = True
    state.dates["1"] = session

    event = _run(
        _service(state), session, date_decision="question", question=VALID_QUESTION
    )

    assert event == "question"
    assert session["question_invalid"] is False


def test_end_keyword_is_recorded_in_the_session():
    state, _ = make_state()
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = 3
    state.dates["1"] = session

    _run(_service(state), session, text="adiós, me voy")

    assert session["end_keyword"] == "adiós"
