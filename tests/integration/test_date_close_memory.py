"""Cierre de cita: marcador explicito, memoria e historial (piezas 1+2+3)."""

import asyncio

from airi.domain.dates import new_date_session
from airi.domain.prompts import date_closed_context_section
from airi.services.date_service import DateService
from airi.testing import FakeUser, make_state

ANA = FakeUser(1, "Ana")
NOW = 1_000_000.0
CHANNEL = 7


def run(coro):
    return asyncio.run(coro)


def _diary_state(texts):
    diary = [
        {"kind": kind, "user_id": "1", "text": text, "ts": float(NOW - (len(texts) - 1 - i))}
        for i, (kind, text) in enumerate(texts)
    ]
    state, _ = make_state(diary=diary)
    return state


def test_closed_section_fires_when_last_diary_is_date_close():
    state = _diary_state(
        [("meet", "La conoci en el canal."), ("date", "La cita termino en paz.")]
    )
    section = date_closed_context_section(state.diary, 1, NOW)
    assert "=== CITA FINALIZADA ===" in section
    assert "EVENTO PASADO" in section
    assert "NO continúes la escena" in section
    assert "La cita termino en paz." in section


def test_closed_section_empty_when_last_diary_is_not_date():
    state = _diary_state(
        [("date", "La cita termino en paz."), ("reflection", "Pienso en ella.")]
    )
    assert date_closed_context_section(state.diary, 1, NOW) == ""


def test_closed_section_empty_without_diary_or_user():
    state, _ = make_state()
    assert date_closed_context_section(state.diary, 1, NOW) == ""
    assert date_closed_context_section(state.diary, None, NOW) == ""


def test_closed_section_only_for_the_date_owner():
    state = _diary_state([("date", "La cita termino en paz.")])
    assert "=== CITA FINALIZADA ===" in date_closed_context_section(
        state.diary, 1, NOW
    )
    assert date_closed_context_section(state.diary, 999, NOW) == ""


def test_finish_date_appends_recap_to_channel_history():
    state, _ = make_state(
        histories={CHANNEL: [{"role": "user", "content": "Ana: hola"}]},
        users={"1": {"name": "Ana"}},
    )
    session = new_date_session("un paseo", 40, now=NOW)
    svc = DateService(state=state, clock=lambda: NOW)
    svc.finish_date(1, session, "ending", now=NOW, channel_id=CHANNEL)
    history = state.histories[CHANNEL]
    assert len(history) == 2
    last = history[-1]
    assert last["role"] == "assistant"
    assert last["content"].startswith("(Cita pasada: un paseo")
    assert "1" not in state.dates


def test_finish_date_without_channel_id_does_not_touch_history():
    state, _ = make_state(
        histories={CHANNEL: [{"role": "user", "content": "Ana: hola"}]},
        users={"1": {"name": "Ana"}},
    )
    session = new_date_session("un paseo", 40, now=NOW)
    svc = DateService(state=state, clock=lambda: NOW)
    svc.finish_date(1, session, "ending", now=NOW)
    assert len(state.histories[CHANNEL]) == 1
    assert "1" not in state.dates


def test_finish_date_uses_llm_summary_when_present():
    state, _ = make_state(users={"1": {"name": "Ana"}})
    session = new_date_session("cena", 40, now=NOW)
    session["summary"] = "Cenamos y hablamos de ramen toda la noche."
    svc = DateService(state=state, clock=lambda: NOW)
    svc.finish_date(1, session, "ending", now=NOW, channel_id=CHANNEL)
    last = state.histories[CHANNEL][-1]
    assert "Cenamos y hablamos de ramen" in last["content"]
    assert state.diary[-1]["text"] == "Cenamos y hablamos de ramen toda la noche."


class _ExplodingLlm:
    async def __call__(self, messages, *, max_tokens=None):
        raise RuntimeError("LLM caido")


def test_timeout_close_falls_back_to_generic_text_when_llm_fails():
    state, _ = make_state(users={"1": {"name": "Ana"}})
    session = new_date_session("una cena", 40, now=NOW - 10000)
    session["turns"] = 2
    state.dates["1"] = session
    svc = DateService(state=state, clock=lambda: NOW, llm_chat=_ExplodingLlm())
    closed = run(svc.finalize_date_summary(1, session, "timeout", now=NOW))
    svc.finish_date(1, session, "timeout", now=NOW, channel_id=CHANNEL)
    assert closed is None
    assert "summary" not in session
    assert "1" not in state.dates
    last = state.histories[CHANNEL][-1]
    assert "se me fue el tiempo" in last["content"]
    assert state.diary[-1]["kind"] == "date"


def test_timeout_close_uses_rich_summary_when_llm_answers():
    async def _llm(messages, *, max_tokens=None):
        return "Paseamos por el parque y nos reimos mucho."
    state, _ = make_state(users={"1": {"name": "Ana"}})
    session = new_date_session("el parque", 40, now=NOW - 10000)
    session["turns"] = 2
    state.dates["1"] = session
    svc = DateService(state=state, clock=lambda: NOW, llm_chat=_llm)
    summary = run(svc.finalize_date_summary(1, session, "timeout", now=NOW))
    svc.finish_date(1, session, "timeout", now=NOW, channel_id=CHANNEL)
    assert summary == "Paseamos por el parque y nos reimos mucho."
    assert "1" not in state.dates
    assert state.diary[-1]["text"] == summary
    assert summary in state.histories[CHANNEL][-1]["content"]
