"""Tests unitarios de la pregunta decisiva de la cita (dominio puro).

Cubren: pregunta única, mínimo de turnos, forzado en el turno 5, roll con RNG
sembrado, clamp de swing ±25 y umbral de crisis en -20.
"""

import random

from airi.domain.constants import (
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

NOW = 1_000_000.0

QUESTION = {
    "text": "¿Qué es lo que más te gusta de mí?",
    "options": [
        {"label": "Cómo me escuchas", "action": "le escuchas atentamente",
         "up_chance": 0.85, "delta_up": 22, "delta_down": -6},
        {"label": "Eres guapa", "action": "le dices que es guapa",
         "up_chance": 0.30, "delta_up": 6, "delta_down": -18},
        {"label": "No sé...", "action": "dudas", "up_chance": 0.55,
         "delta_up": 12, "delta_down": -12},
    ],
}


# --- normalize_date_session (compat con sesiones viejas) -------------------

def test_normalize_adds_question_fields_to_old_session():
    old = {"scene": "paseo", "state": "active", "turns": 3, "history": []}

    session = normalize_date_session(old)

    assert session["question"] is None
    assert session["question_used"] is False
    assert session["question_pending"] is False
    assert session["question_forced"] is False
    assert session["question_asked_at"] == 0.0


# --- question_allowed (mínimo de turnos + única) --------------------------

def test_question_not_allowed_before_min_turns():
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = DATE_QUESTION_MIN_TURNS - 1

    assert question_allowed(session) is False


def test_question_allowed_from_min_turns_onwards():
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = DATE_QUESTION_MIN_TURNS

    assert question_allowed(session) is True


def test_question_only_once_per_date():
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = DATE_QUESTION_MIN_TURNS
    session["question_used"] = True

    assert question_allowed(session) is False


def test_question_not_allowed_while_pending():
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = DATE_QUESTION_MIN_TURNS
    session["question_pending"] = True

    assert question_allowed(session) is False


def test_question_not_allowed_outside_active():
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = DATE_QUESTION_MIN_TURNS
    session["state"] = "last_chance"

    assert question_allowed(session) is False


# --- should_force_question (turno 5) --------------------------------------

def test_should_force_at_force_turn_when_not_used():
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = DATE_QUESTION_FORCE_TURN

    assert should_force_question(session) is True


def test_should_not_force_before_force_turn():
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = DATE_QUESTION_FORCE_TURN - 1

    assert should_force_question(session) is False


def test_should_not_force_when_already_used():
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = DATE_QUESTION_FORCE_TURN + 2
    session["question_used"] = True

    assert should_force_question(session) is False


# --- step_date con decision="question" -------------------------------------

def _active_session(turns):
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = turns
    return session


def test_step_date_question_stores_and_marks_pending():
    session = _active_session(DATE_QUESTION_MIN_TURNS)

    state, event = step_date(
        session, decision="question", question=QUESTION, now=NOW
    )

    assert (state, event) == ("active", "question")
    assert session["question"] == QUESTION
    assert session["question_used"] is True
    assert session["question_pending"] is True
    assert session["question_asked_at"] == NOW


def test_step_date_question_too_early_is_ignored():
    session = _active_session(0)

    state, event = step_date(
        session, points=40, decision="question", question=QUESTION,
        now=NOW, allow_crisis_drop=False,
    )

    # No se guarda: se trata como un turno normal.
    assert event == "continue"
    assert session["question"] is None
    assert session["question_pending"] is False


def test_step_date_question_twice_only_first_counts():
    session = _active_session(DATE_QUESTION_MIN_TURNS)
    step_date(session, points=40, decision="question", question=QUESTION,
              now=NOW, allow_crisis_drop=False)

    state, event = step_date(
        session, points=40, decision="question", question=QUESTION,
        now=NOW, allow_crisis_drop=False,
    )

    assert event == "continue"
    assert session["question_pending"] is True  # la primera sigue viva


def test_step_date_question_requires_dict_question():
    session = _active_session(DATE_QUESTION_MIN_TURNS)

    state, event = step_date(
        session, points=40, decision="question", question=None,
        now=NOW, allow_crisis_drop=False,
    )

    assert event == "continue"
    assert session["question_used"] is False


# --- roll_question (RNG sembrado + clamp) ---------------------------------

def test_roll_with_seeded_rng_is_deterministic():
    option = {"up_chance": 0.5, "delta_up": 10, "delta_down": -8}

    first = [roll_question(option, random.Random(42)) for _ in range(1)]
    second = [roll_question(option, random.Random(42)) for _ in range(1)]

    assert first == second


def test_roll_win_at_chance_one():
    option = {"up_chance": 1.0, "delta_up": 10, "delta_down": -8}

    win, delta = roll_question(option, random.Random(1))

    assert win is True
    assert delta == 10


def test_roll_fail_at_chance_zero():
    option = {"up_chance": 0.0, "delta_up": 10, "delta_down": -8}

    win, delta = roll_question(option, random.Random(1))

    assert win is False
    assert delta == -8


def test_roll_clamps_up_to_delta_max():
    option = {"up_chance": 1.0, "delta_up": 999, "delta_down": 0}

    win, delta = roll_question(option, random.Random(1))

    assert delta == DATE_QUESTION_DELTA_MAX


def test_roll_clamps_down_to_minus_delta_max():
    option = {"up_chance": 0.0, "delta_up": 0, "delta_down": -999}

    win, delta = roll_question(option, random.Random(1))

    assert delta == -DATE_QUESTION_DELTA_MAX


def test_roll_enforces_sign_on_misdeclared_deltas():
    # El modelo puede equivocarse de signo: gana → delta no negativo;
    # pierde → delta no positivo.
    win, delta = roll_question(
        {"up_chance": 1.0, "delta_up": -30, "delta_down": -9}, random.Random(1)
    )
    assert win and delta == 0

    win, delta = roll_question(
        {"up_chance": 0.0, "delta_up": 9, "delta_down": 30}, random.Random(1)
    )
    assert not win and delta == 0


def test_roll_invalid_option_returns_no_change():
    assert roll_question(None, random.Random(1)) == (False, 0)
    assert roll_question("no dict", random.Random(1)) == (False, 0)


# --- question_failed_hard (umbral -20) -------------------------------------

def test_hard_fail_at_minus_20():
    assert question_failed_hard(-DATE_QUESTION_CRISIS_DROP) is True


def test_hard_fail_below_threshold_is_not_hard():
    assert question_failed_hard(-19) is False
    assert question_failed_hard(-5) is False


def test_hard_fail_never_on_positive_delta():
    assert question_failed_hard(25) is False
    assert question_failed_hard(0) is False


# --- question_option -------------------------------------------------------

def test_question_option_returns_option_by_index():
    session = new_date_session("paseo", 40, now=NOW)
    session["question"] = QUESTION

    assert question_option(session, 1) == QUESTION["options"][1]


def test_question_option_out_of_range_or_invalid():
    session = new_date_session("paseo", 40, now=NOW)
    session["question"] = QUESTION

    assert question_option(session, 3) is None
    assert question_option(session, -1) is None
    assert question_option(session, "x") is None
    assert question_option({"question": None}, 0) is None


# --- parse_date_question ---------------------------------------------------

def test_parse_date_question_happy_path():
    parsed = parse_date_question(QUESTION)

    assert parsed["text"] == QUESTION["text"]
    assert len(parsed["options"]) == 3
    first = parsed["options"][0]
    assert first["label"] == "Cómo me escuchas"
    assert first["up_chance"] == 0.85
    assert first["delta_up"] == 22
    assert first["delta_down"] == -6


def test_parse_date_question_caps_options_and_chance():
    raw = {
        "text": "¿Y ahora qué?",
        "options": [
            {"label": f"op{i}", "action": "a", "up_chance": 5,
             "delta_up": 1, "delta_down": -1}
            for i in range(6)
        ],
    }

    parsed = parse_date_question(raw)

    assert len(parsed["options"]) == 3
    assert all(o["up_chance"] == 1.0 for o in parsed["options"])


def test_parse_date_question_fixes_option_signs():
    raw = {
        "text": "¿Eres de día o de noche?",
        "options": [
            {"label": "bueno", "action": "a", "up_chance": 0.5,
             "delta_up": -10, "delta_down": 7},
        ],
    }

    parsed = parse_date_question(raw)

    assert parsed["options"][0]["delta_up"] == 0
    assert parsed["options"][0]["delta_down"] == 0


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
        "options": [{"action": "lo que sea", "up_chance": 0.5,
                     "delta_up": 1, "delta_down": -1}],
    })

    assert parsed["options"][0]["label"] == "lo que sea"


# --- parse_model_output integra date_question ------------------------------

def test_parse_model_output_propagates_date_question():
    import json

    raw = json.dumps({
        "reply": "Airi te mira fijamente.",
        "gif": "none", "memory": "none", "diary": "none",
        "affinity_delta": 0, "affinity_event": "none",
        "date_decision": "question", "date_reason": "quiere saberlo",
        "last_chance_result": "none", "date_question": QUESTION,
    })

    output = parse_model_output(raw)

    assert output.date_decision == "question"
    assert output.date_question["text"] == QUESTION["text"]
    assert len(output.date_question["options"]) == 3


def test_parse_model_output_without_date_question_is_none():
    import json

    raw = json.dumps({
        "reply": "Hola.",
        "gif": "none", "memory": "none", "diary": "none",
        "affinity_delta": 0, "affinity_event": "none",
        "date_decision": "continue", "date_reason": "none",
        "last_chance_result": "none",
    })

    output = parse_model_output(raw)

    assert output.date_question is None
