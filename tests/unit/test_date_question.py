"""Tests unitarios de la pregunta decisiva de la cita (dominio puro).

Cubren: la pregunta solo puede hacerse una vez por cita y pasados unos
turnos, la red de seguridad de la pregunta de reserva, el dado de las
alternativas con su tope de swing y el saneado de la pregunta que propone el
modelo (texto no fiable).
"""

from __future__ import annotations

import random

from airi.domain import dates
from airi.domain.constants import (
    DATE_MAX_TURNS,
    DATE_QUESTION_CRISIS_DROP,
    DATE_QUESTION_DELTA_MAX,
    DATE_QUESTION_FORCE_TURN,
    DATE_QUESTION_MIN_TURNS,
)
from airi.domain.dates import (
    new_date_session,
    normalize_date_session,
    question_allowed,
    question_failed_hard,
    question_option,
    roll_question,
    should_force_question,
    step_date,
)
from airi.domain.llm_output import parse_date_question, parse_model_output
from airi.domain.texts import DATE_QUESTION_FALLBACK

NOW = 1_000_000.0

QUESTION = {
    "text": "¿Qué es lo que más te gusta de mí?",
    "options": [
        {
            "label": "Tu risa",
            "action": "le digo que su risa",
            "up_chance": 0.8,
            "delta_up": 20,
            "delta_down": -8,
        },
        {
            "label": "Tu compañía",
            "action": "le digo que su compañía",
            "up_chance": 0.4,
            "delta_up": 12,
            "delta_down": -6,
        },
    ],
}


def _session(turns=0, state="active"):
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = turns
    session["state"] = state
    return session


# --- normalize_date_session ------------------------------------------------


def test_normalize_adds_question_fields_to_old_session():
    old = {"scene": "paseo", "state": "active", "turns": 3, "history": []}
    session = normalize_date_session(old)
    assert session["question"] is None
    assert session["question_used"] is False
    assert session["question_pending"] is False
    assert session["question_forced"] is False


# --- question_allowed ------------------------------------------------------


def test_question_not_allowed_before_min_turns():
    session = _session(DATE_QUESTION_MIN_TURNS - 1)
    assert question_allowed(session) is False


def test_question_allowed_from_min_turns_onwards():
    assert question_allowed(_session(DATE_QUESTION_MIN_TURNS)) is True


def test_question_only_once_per_date():
    session = _session(DATE_QUESTION_MIN_TURNS)
    session["question_used"] = True
    assert question_allowed(session) is False


def test_question_not_allowed_while_pending():
    session = _session(DATE_QUESTION_MIN_TURNS)
    session["question_pending"] = True
    assert question_allowed(session) is False


def test_question_not_allowed_outside_active():
    session = _session(DATE_QUESTION_MIN_TURNS, state="last_chance")
    assert question_allowed(session) is False


# --- should_force_question -------------------------------------------------


def test_should_force_at_force_turn_when_not_used():
    assert should_force_question(_session(DATE_QUESTION_FORCE_TURN)) is True


def test_should_not_force_before_force_turn():
    assert should_force_question(_session(DATE_QUESTION_FORCE_TURN - 1)) is False


def test_should_not_force_if_already_used():
    session = _session(DATE_QUESTION_FORCE_TURN)
    session["question_used"] = True
    assert should_force_question(session) is False


# --- step_date con decision="question" --------------------------------------


def test_step_date_question_stores_and_marks_pending():
    session = _session(DATE_QUESTION_MIN_TURNS - 1)
    state, event = step_date(
        session, decision="question", question=QUESTION, points=40, now=NOW
    )
    assert (state, event) == ("active", "question")
    assert session["question"] == QUESTION
    assert session["question_used"] is True
    assert session["question_pending"] is True
    assert session["question_forced"] is False


def test_step_date_question_too_early_is_ignored(monkeypatch):
    """Con un mínimo de turnos mayor, la pregunta se rechaza hasta llegar a él."""
    monkeypatch.setattr(dates, "DATE_QUESTION_MIN_TURNS", 3)
    session = _session(0)
    state, event = step_date(
        session, decision="question", question=QUESTION, points=40, now=NOW
    )
    assert event == "continue"
    assert session["question"] is None
    assert session["question_pending"] is False

    # Ya con los turnos mínimos, la pregunta se acepta.
    session = _session(2)
    state, event = step_date(
        session, decision="question", question=QUESTION, points=40, now=NOW
    )
    assert event == "question"


def test_step_date_question_twice_only_first_counts():
    session = _session(DATE_QUESTION_MIN_TURNS - 1)
    step_date(session, decision="question", question=QUESTION, points=40, now=NOW)
    state, event = step_date(
        session, decision="question", question=QUESTION, points=40, now=NOW
    )
    assert event == "continue"
    assert session["question_pending"] is True  # la primera sigue viva


def test_step_date_question_without_payload_is_ignored():
    session = _session(DATE_QUESTION_MIN_TURNS - 1)
    state, event = step_date(
        session, decision="question", question=None, points=40, now=NOW
    )
    assert event == "continue"
    assert session["question_used"] is False


def test_forced_question_launches_the_reserve_at_the_force_turn():
    """Si la IA no la hace, la pregunta de reserva se lanza igualmente."""
    session = _session(DATE_QUESTION_FORCE_TURN - 1)
    state, event = step_date(
        session,
        decision="continue",
        points=40,
        now=NOW,
        fallback_question=DATE_QUESTION_FALLBACK,
    )
    assert (state, event) == ("active", "question")
    assert session["question_forced"] is True
    assert session["question"]["options"]
    # La reserva nunca provoca una crisis por fallo grave.
    for option in DATE_QUESTION_FALLBACK["options"]:
        assert not question_failed_hard(int(option["delta_down"]))


def test_reserve_question_is_copied_not_shared():
    session = _session(DATE_QUESTION_FORCE_TURN - 1)
    step_date(
        session,
        decision="continue",
        points=40,
        now=NOW,
        fallback_question=DATE_QUESTION_FALLBACK,
    )
    session["question"]["options"][0]["label"] = "MUTADO"
    assert DATE_QUESTION_FALLBACK["options"][0]["label"] != "MUTADO"


def test_the_date_still_ends_when_the_turn_limit_arrives():
    session = _session(DATE_MAX_TURNS - 1)
    state, event = step_date(
        session,
        decision="continue",
        points=40,
        now=NOW,
        fallback_question=DATE_QUESTION_FALLBACK,
    )
    assert event == "ending"
    assert session["state"] == "final_scene"


# --- roll_question ---------------------------------------------------------


def test_roll_with_seeded_rng_is_deterministic():
    option = {"up_chance": 0.5, "delta_up": 10, "delta_down": -8}
    first = roll_question(option, random.Random(42))
    second = roll_question(option, random.Random(42))
    assert first == second


def test_roll_clamps_the_swing():
    option = {"up_chance": 1.0, "delta_up": 999, "delta_down": 0}
    win, delta = roll_question(option, random.Random(1))
    assert win and delta == DATE_QUESTION_DELTA_MAX

    option = {"up_chance": 0.0, "delta_up": 0, "delta_down": -999}
    win, delta = roll_question(option, random.Random(1))
    assert not win and delta == -DATE_QUESTION_DELTA_MAX


def test_roll_fixes_the_sign():
    option = {"up_chance": 1.0, "delta_up": -30, "delta_down": -9}
    win, delta = roll_question(option, random.Random(1))
    assert win and delta == 0

    option = {"up_chance": 0.0, "delta_up": 9, "delta_down": 30}
    win, delta = roll_question(option, random.Random(1))
    assert not win and delta == 0


def test_roll_invalid_option_returns_no_change():
    assert roll_question(None, random.Random(1)) == (False, 0)
    assert roll_question("no dict", random.Random(1)) == (False, 0)
    # Una alternativa sin deltas no mueve la afinidad (el signo se corrige).
    assert roll_question({"up_chance": 0.5}, random.Random(1)) == (True, 0)


# --- question_failed_hard --------------------------------------------------


def test_hard_fail_at_the_crisis_threshold():
    assert question_failed_hard(-DATE_QUESTION_CRISIS_DROP) is True
    assert question_failed_hard(-(DATE_QUESTION_CRISIS_DROP - 1)) is False
    assert question_failed_hard(5) is False


# --- question_option --------------------------------------------------------


def test_question_option_returns_option_by_index():
    session = _session(DATE_QUESTION_MIN_TURNS)
    session["question"] = QUESTION
    assert question_option(session, 1) == QUESTION["options"][1]
    assert question_option(session, 5) is None
    assert question_option(session, -1) is None
    assert question_option({"question": None}, 0) is None


# --- parse_date_question ----------------------------------------------------


def test_parse_date_question_happy_path():
    parsed = parse_date_question(QUESTION)
    assert parsed["text"] == QUESTION["text"]
    assert len(parsed["options"]) == 2


def test_parse_date_question_fixes_option_signs():
    parsed = parse_date_question({
        "text": "¿Y ahora qué?",
        "options": [{
            "label": "x", "action": "y", "up_chance": 2.0,
            "delta_up": -10, "delta_down": 10,
        }],
    })
    option = parsed["options"][0]
    assert option["up_chance"] == 1.0
    assert option["delta_up"] == 0
    assert option["delta_down"] == 0


def test_parse_date_question_rejects_garbage():
    assert parse_date_question(None) is None
    assert parse_date_question("texto") is None
    assert parse_date_question({"text": "", "options": []}) is None
    assert parse_date_question({"text": "¿x?", "options": "no list"}) is None
    assert parse_date_question({"text": "¿x?", "options": []}) is None
    assert parse_date_question(
        {"text": "¿x?", "options": [{"label": "sin action"}]}
    ) is None


def test_parse_date_question_label_falls_back_to_action():
    parsed = parse_date_question({
        "text": "¿Y tú?",
        "options": [{"action": "lo que sea", "up_chance": 0.5}],
    })
    assert parsed["options"][0]["label"] == "lo que sea"


def test_parse_model_output_propagates_date_question():
    import json

    raw = json.dumps({
        "reply": "hola", "gif": "none", "memory": "none", "diary": "none",
        "affinity_delta": 0, "affinity_event": "none",
        "date_decision": "question", "date_reason": "quiere saberlo",
        "last_chance_result": "none", "date_question": QUESTION,
    })
    output = parse_model_output(raw)
    assert output.date_decision == "question"
    assert output.date_question["text"] == QUESTION["text"]
    assert len(output.date_question["options"]) == 2


def test_parse_model_output_without_date_question_is_none():
    output = parse_model_output('{"reply": "hola"}')
    assert output.date_question is None
