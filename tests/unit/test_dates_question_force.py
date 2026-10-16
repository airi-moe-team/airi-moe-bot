"""Tests de la red de seguridad de la pregunta decisiva (1.2 / D2).

Si el modelo nunca propone la pregunta, al final de la gracia se lanza una
pregunta de reserva determinista para que el evento `question` SIEMPRE ocurra.
"""

from airi.domain.constants import (
    DATE_MAX_TURNS,
    DATE_QUESTION_DELTA_MAX,
    DATE_QUESTION_FORCE_TURN,
    DATE_QUESTION_GRACE_TURNS,
)
from airi.domain.dates import new_date_session, question_failed_hard, step_date
from airi.domain.texts import DATE_QUESTION_FALLBACK

NOW = 1_000_000.0

MODEL_QUESTION = {
    "text": "¿Te gusto?",
    "options": [
        {"label": "sí", "action": "sonríe", "up_chance": 1.0,
         "delta_up": 6, "delta_down": -6},
    ],
}


def _session(turns=0):
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = turns
    return session


def test_no_question_before_grace():
    session = _session(0)
    for _ in range(DATE_MAX_TURNS):
        _, event = step_date(
            session, points=40, fallback_question=DATE_QUESTION_FALLBACK, now=NOW
        )
        assert event == "continue"
    assert session["question_used"] is False


def test_forced_question_at_grace_end():
    session = _session(DATE_MAX_TURNS + DATE_QUESTION_GRACE_TURNS - 1)

    state, event = step_date(
        session, points=40, fallback_question=DATE_QUESTION_FALLBACK, now=NOW
    )

    assert (state, event) == ("active", "question")
    assert session["question_forced"] is True
    assert session["question_pending"] is True
    assert session["question_used"] is True
    assert session["question"]["options"]


def test_forced_question_prefers_model_payload():
    session = _session(DATE_MAX_TURNS + DATE_QUESTION_GRACE_TURNS - 1)

    _, event = step_date(
        session,
        points=40,
        question=MODEL_QUESTION,
        fallback_question=DATE_QUESTION_FALLBACK,
        now=NOW,
    )

    assert event == "question"
    assert session["question_forced"] is True
    assert session["question"]["text"] == "¿Te gusto?"


def test_fallback_payload_is_copied_not_shared():
    session = _session(DATE_MAX_TURNS + DATE_QUESTION_GRACE_TURNS - 1)
    step_date(session, points=40, fallback_question=DATE_QUESTION_FALLBACK, now=NOW)

    session["question"]["options"][0]["label"] = "MUTADO"

    assert DATE_QUESTION_FALLBACK["options"][0]["label"] != "MUTADO"


def test_fallback_never_causes_hard_fail_crisis():
    for option in DATE_QUESTION_FALLBACK["options"]:
        assert not question_failed_hard(int(option["delta_down"]))
        assert abs(int(option["delta_up"])) <= DATE_QUESTION_DELTA_MAX
        assert abs(int(option["delta_down"])) <= DATE_QUESTION_DELTA_MAX


def test_question_already_used_restores_the_plain_limit():
    session = _session(DATE_MAX_TURNS - 1)
    session["question_used"] = True

    state, event = step_date(
        session, points=40, fallback_question=DATE_QUESTION_FALLBACK, now=NOW
    )

    assert event == "ending"
    assert session["state"] == "final_scene"


def test_model_question_is_not_flagged_as_forced():
    session = _session(2)

    state, event = step_date(
        session,
        points=40,
        decision="question",
        question=MODEL_QUESTION,
        fallback_question=DATE_QUESTION_FALLBACK,
        now=NOW,
    )

    assert event == "question"
    assert session["question_forced"] is False


def test_force_turn_is_before_max_turns():
    # Invariante del diseño: la gracia empieza antes del tope duro.
    assert DATE_QUESTION_FORCE_TURN < DATE_MAX_TURNS
