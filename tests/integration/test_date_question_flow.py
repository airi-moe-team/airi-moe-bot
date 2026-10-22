"""Integración de la pregunta decisiva: pegamentos, swing y crisis forzada.

El motor tira el dado de la alternativa elegida, aplica el swing (que es más
grande que el cambio normal de afinidad) y, si el fallo es grave, fuerza la
crisis: la cita pasa a la última oportunidad.
"""


from airi.discord_bot.client import build_date_glue
from airi.domain.constants import DATE_QUESTION_CRISIS_DROP
from airi.domain.dates import new_date_session, step_date
from airi.testing import FakeUser, make_state

ANA = FakeUser(1, "Ana")
NOW = 1_000_000.0

QUESTION = {
    "text": "¿Qué es lo que más te gusta de mí?",
    "options": [
        {
            "label": "Tu risa",
            "action": "le digo que su risa",
            "up_chance": 1.0,
            "delta_up": 20,
            "delta_down": -8,
        },
        {
            "label": "Una tontería",
            "action": "le digo una tontería",
            "up_chance": 0.0,
            "delta_up": 5,
            "delta_down": -22,
        },
    ],
}


def _glue(state):
    return build_date_glue(state, llm_url="http://x", request_timeout=5)


def _session(state):
    session = new_date_session("paseo", 40, now=NOW)
    session["question"] = QUESTION
    session["question_used"] = True
    session["question_pending"] = True
    state.dates["1"] = session
    return session


def test_resolve_question_returns_the_rolled_result():
    state, _ = make_state()
    glue = _glue(state)
    session = _session(state)

    result = glue.resolve_question(session, 0)

    assert result is not None
    assert result["win"] is True
    assert result["delta"] == 20
    assert result["index"] == 0
    assert result["action"] == "le digo que su risa"


def test_resolve_question_returns_none_for_an_unknown_option():
    state, _ = make_state()
    glue = _glue(state)
    session = _session(state)

    assert glue.resolve_question(session, 9) is None


def test_apply_question_result_moves_the_affinity_with_its_own_cap():
    """El swing de la pregunta (±25) NO se recorta al cambio normal (±5)."""
    state, _ = make_state(affinity={"1": {"points": 40}})
    glue = _glue(state)
    session = _session(state)

    result = glue.resolve_question(session, 0)
    glue.apply_question_result(session, result, user_id=1, now=NOW)

    assert state.entry_points(1) == 60
    assert session["question_pending"] is False
    assert session["question_result"]["win"] is True


def test_a_hard_failure_forces_the_crisis():
    state, _ = make_state(affinity={"1": {"points": 40}})
    glue = _glue(state)
    session = _session(state)

    result = glue.resolve_question(session, 1)
    glue.apply_question_result(session, result, user_id=1, now=NOW)

    assert result["win"] is False
    assert result["delta"] <= -DATE_QUESTION_CRISIS_DROP
    assert session["force_crisis"] is True
    # La crisis se dispara en el siguiente turno de la cita.
    state_, event = step_date(session, decision="continue", points=40, now=NOW)
    assert event == "crisis"
    assert state_ == "last_chance"


def test_expire_question_cancels_the_pending_question():
    state, _ = make_state()
    glue = _glue(state)
    session = _session(state)

    assert glue.expire_question(1) is True
    assert session["question_pending"] is False
    # Una segunda caducidad no hace nada.
    assert glue.expire_question(1) is False


def test_expire_question_ignores_unknown_users():
    state, _ = make_state()
    glue = _glue(state)

    assert glue.expire_question(404) is False
