"""Tests de integración del flujo de citas con DateService (sin Discord)."""

import asyncio

from airi.domain.constants import DATE_MAX_TURNS, DATE_QUESTION_GRACE_TURNS
from airi.domain.dates import new_date_session
from airi.domain.texts import DATE_CRISIS_TEXT
from airi.services.date_service import DateService
from airi.testing import FakeNotifier, FakeUser, make_state

ANA = FakeUser(1, "Ana")
NOW = 1_000_000.0


def make_service(state, notifier, llm_chat=None):
    return DateService(
        state=state, notifier=notifier, clock=lambda: NOW, llm_chat=llm_chat
    )


def run(coro):
    return asyncio.run(coro)


def step(service, session, **kw):
    defaults = dict(
        user=ANA, text="hola", delta=0, points=40,
        date_decision="continue", date_reason="none",
        last_chance_result="none", now=NOW,
    )
    defaults.update(kw)
    return run(service.process_turn(session, **defaults))


QUESTION = {
    "text": "Oye... ¿qué es lo que más te gusta de mí?",
    "options": [
        {"label": "Cómo me escuchas", "action": "le escuchas atentamente",
         "up_chance": 1.0, "delta_up": 20, "delta_down": -5},
        {"label": "Eres guapa", "action": "le dices que es guapa",
         "up_chance": 0.0, "delta_up": 6, "delta_down": -22},
        {"label": "No sé...", "action": "dudas", "up_chance": 0.55,
         "delta_up": 12, "delta_down": -12},
    ],
}


def _question_session(state, turns=2):
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = turns
    state.dates["1"] = session
    state.users["1"] = {"name": "Ana"}
    return session


def test_continue_saves_without_messages():
    state, counters = make_state()
    session = new_date_session("paseo", 40, now=NOW)
    state.dates["1"] = session
    notifier = FakeNotifier()
    service = make_service(state, notifier)

    event = step(service, session)

    assert event == "continue"
    assert notifier.sent == []
    assert counters["dates"] == 1
    assert session["turns"] == 1
    assert session["state"] == "active"


def test_crisis_notifies_and_enters_last_chance():
    state, counters = make_state()
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = 3  # DATE_CRISIS_MIN_TURNS
    state.dates["1"] = session
    notifier = FakeNotifier()
    service = make_service(state, notifier)

    event = step(service, session, date_decision="crisis", date_reason="se incomodó",
                 points=36)

    assert event == "crisis"
    assert session["state"] == "last_chance"
    assert session["crisis_reason"] == "se incomodó"
    assert notifier.sent == [DATE_CRISIS_TEXT]
    assert counters["dates"] == 1


def test_end_keyword_closes_and_logs_diary():
    state, _ = make_state()
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = 4
    state.dates["1"] = session
    state.users["1"] = {"name": "Ana"}
    notifier = FakeNotifier()
    service = make_service(state, notifier)

    event = step(service, session, text="adiós, nos vemos")

    assert event == "ending"
    assert "1" not in state.dates
    assert session["state"] == "closed"
    assert any(e.get("kind") == "date" for e in state.diary)
    assert notifier.sent  # mensaje de cierre


# --- resumen de cierre en el diario -----------------------------------------

def test_date_ends_records_summary():
    """Con LLM inyectado, el cierre guarda el resumen que devuelve el modelo."""
    state, _ = make_state()
    session = new_date_session("una cena a la luz de las velas", 40, now=NOW)
    session["turns"] = 4
    session["history"] = [
        {"role": "user", "content": "Ana: llegué antes"},
        {"role": "assistant", "content": '{"reply":"*sonríe* Yo también~"}'},
    ]
    state.dates["1"] = session
    state.users["1"] = {"name": "Ana"}
    captured = {}

    async def fake_llm(messages, *, max_tokens=None):
        captured["messages"] = messages
        captured["max_tokens"] = max_tokens
        return "Recordaré la cena con Ana: se portó de maravilla conmigo."

    service = make_service(state, FakeNotifier(), llm_chat=fake_llm)

    event = step(service, session, text="adiós")

    assert event == "ending"
    dates = [e for e in state.diary if e.get("kind") == "date"]
    assert len(dates) == 1
    assert dates[0]["text"] == "Recordaré la cena con Ana: se portó de maravilla conmigo."
    # El prompt incluye la escena y el diálogo privado de la cita.
    prompt = captured["messages"][0]["content"]
    assert "una cena a la luz de las velas" in prompt
    assert "llegué antes" in prompt
    assert captured["max_tokens"] is not None


def test_date_ends_falls_back_without_llm():
    """Sin LLM inyectado, el cierre usa el texto genérico determinista."""
    state, _ = make_state()
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = 4
    state.dates["1"] = session
    state.users["1"] = {"name": "Ana"}
    service = make_service(state, FakeNotifier())

    step(service, session, text="adiós")

    dates = [e for e in state.diary if e.get("kind") == "date"]
    assert len(dates) == 1
    assert "Ana" in dates[0]["text"]
    assert "paseo" in dates[0]["text"]


def test_date_ends_falls_back_on_llm_error():
    """Si el resumen falla, el diario conserva el texto genérico (una entrada)."""
    state, _ = make_state()
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = 4
    session["history"] = [{"role": "user", "content": "Ana: hola"}]
    state.dates["1"] = session
    state.users["1"] = {"name": "Ana"}

    async def boom(messages, *, max_tokens=None):
        raise RuntimeError("llama caído")

    service = make_service(state, FakeNotifier(), llm_chat=boom)

    event = step(service, session, text="adiós")

    assert event == "ending"
    assert "summary" not in session
    dates = [e for e in state.diary if e.get("kind") == "date"]
    assert len(dates) == 1
    assert "paseo" in dates[0]["text"]


def test_recovery_applies_affinity_and_closes():
    state, _ = make_state(affinity={"1": {"points": 36, "last_interaction": NOW,
                                          "last_gain": 0.0, "milestones": []}})
    session = new_date_session("paseo", 40, now=NOW)
    session["state"] = "last_chance"
    session["last_chance_used"] = True
    session["turns"] = 3
    state.dates["1"] = session
    state.users["1"] = {"name": "Ana"}
    notifier = FakeNotifier()
    service = make_service(state, notifier)

    event = step(service, session, points=36, last_chance_result="success")

    assert event == "recovered"
    # Recuperación = min(12, 40 - 36) = 4.
    assert state.entry_points(1) == 40
    assert "1" not in state.dates


def test_failed_last_chance_closes_without_recovery():
    state, _ = make_state(affinity={"1": {"points": 30, "last_interaction": NOW,
                                          "last_gain": 0.0, "milestones": []}})
    session = new_date_session("paseo", 40, now=NOW)
    session["state"] = "last_chance"
    session["last_chance_used"] = True
    session["turns"] = 3
    state.dates["1"] = session
    state.users["1"] = {"name": "Ana"}
    service = make_service(state, FakeNotifier())

    event = step(service, session, points=30, last_chance_result="fail")

    assert event == "failed_last_chance"
    assert state.entry_points(1) == 30  # sin recuperación
    assert "1" not in state.dates


def test_full_date_happy_path():
    """Si el modelo nunca pregunta, al final de la gracia se fuerza la pregunta."""
    state, _ = make_state()
    session = new_date_session("cena", 40, now=NOW)
    state.dates["1"] = session
    state.users["1"] = {"name": "Ana"}
    notifier = FakeNotifier()
    service = make_service(state, notifier)

    total = DATE_MAX_TURNS + DATE_QUESTION_GRACE_TURNS
    events = [step(service, session) for _ in range(total)]

    # El tope se amplía con la gracia y la pregunta decisiva se fuerza (reserva
    # determinista): el evento final es "question", no un cierre mudo.
    assert events[-1] == "question"
    assert session["question_forced"] is True
    assert session["question_pending"] is True
    assert session["state"] == "active"
    assert "1" in state.dates
    assert notifier.sent == []  # el cierre aún no ha ocurrido


# --- turno de la pregunta -----------------------------------------------------

def test_question_turn_stores_question_without_affinity_swing():
    state, counters = make_state()
    session = _question_session(state)
    notifier = FakeNotifier()
    service = make_service(state, notifier)

    event = step(service, session, date_decision="question",
                 date_reason="quiere saberlo", question=QUESTION)

    assert event == "question"
    assert session["question_pending"] is True
    assert session["question_used"] is True
    assert session["state"] == "active"
    # El motor no tira el dado aquí: no hay mensajes ni cambios.
    assert notifier.sent == []
    assert counters["affinity"] == 0
    assert counters["dates"] == 1
    assert "1" in state.dates


def test_question_answer_win_applies_swing_and_clears_pending():
    state, counters = make_state(
        affinity={"1": {"points": 40, "last_interaction": NOW,
                          "last_gain": 0.0, "milestones": []}}
    )
    session = _question_session(state)
    service = make_service(state, FakeNotifier())
    step(service, session, date_decision="question",
         date_reason="quiere saberlo", question=QUESTION)

    # El jugador pulsa la opción 0 (up_chance=1.0 → acierto seguro +20).
    result = service.resolve_question(session, 0)
    applied = service.apply_question_result(
        session, result, user_id=1, now=NOW
    )

    assert result["win"] is True
    assert applied == 20
    assert state.entry_points(1) == 60
    assert session["question_pending"] is False
    assert "1" in state.dates  # la cita sigue
    assert counters["affinity"] == 1


def test_question_answer_hard_fail_marks_force_crisis():
    state, _ = make_state()
    session = _question_session(state)
    service = make_service(state, FakeNotifier())
    step(service, session, date_decision="question",
         date_reason="quiere saberlo", question=QUESTION)

    # Opción 1 (up_chance=0.0 → fallo -22: supera el umbral -20).
    result = service.resolve_question(session, 1)
    service.apply_question_result(session, result, user_id=1, now=NOW)

    assert result["win"] is False
    assert result["hard_fail"] is True
    assert session["force_crisis"] is True


def test_reaction_turn_after_hard_fail_enters_last_chance():
    state, _ = make_state(
        affinity={"1": {"points": 40, "last_interaction": NOW,
                          "last_gain": 0.0, "milestones": []}}
    )
    session = _question_session(state)
    notifier = FakeNotifier()
    service = make_service(state, notifier)
    step(service, session, date_decision="question",
         date_reason="quiere saberlo", question=QUESTION)
    # El pulso ya resolvió: swing -22 aplicado + `force_crisis`.
    result = service.resolve_question(session, 1)
    service.apply_question_result(session, result, user_id=1, now=NOW)

    # Turno extra de reacción: el LLM solo comenta (delta 0, sin caída por
    # afinidad). run_user_turn manda `decision="crisis"` si hay `force_crisis`.
    event = step(service, session, text="reacciona dolida",
                 date_decision="crisis", date_reason="none",
                 allow_crisis_drop=False)

    assert event == "crisis"
    assert session["state"] == "last_chance"
    assert notifier.sent == [DATE_CRISIS_TEXT]


def test_question_ignored_before_min_turns():
    state, _ = make_state()
    session = _question_session(state, turns=0)
    service = make_service(state, FakeNotifier())

    event = step(service, session, date_decision="question",
                 date_reason="demasiado pronto", question=QUESTION)

    assert event == "continue"
    assert session["question_used"] is False
