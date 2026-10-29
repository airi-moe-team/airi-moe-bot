"""El turno rápido se desactiva cuando el contexto reciente del canal es mixto.

Un mensaje corto de un canal donde también habló otra persona (o donde Airi
respondió dirigida a otra) merece el prompt y el historial completos: es justo
cuando más importa distinguir a quién va dirigido cada sentimiento.

Basado en la traza reproducida `traces/2026-10-22/ab7d586c2fb5.json`.
"""

from __future__ import annotations

import asyncio

from airi.services.conversation import QUICK_HISTORY_MESSAGES, ConversationService, TurnContext
from airi.testing import FakeLLM, FakeUser, llm_json, make_state


def _service(llm, state):
    return ConversationService(llm=llm, state=state, clock=lambda: 1_000_000.0)


def _history_with_other_user(uid):
    someone_else = str(1000 + int(uid))
    history = []
    for i in range(QUICK_HISTORY_MESSAGES):
        history.append({
            "role": "user",
            "content": "hola a todos",
            "author_id": someone_else,
            "author_name": "Otro",
        })
    return history


def test_short_message_with_other_speaker_recently_uses_full_contract():
    state, _ = make_state()
    state.histories[0] = _history_with_other_user(42)
    llm = FakeLLM(replies=[llm_json("hola")])
    david = FakeUser(42, "David")
    svc = _service(llm, state)

    asyncio.run(svc.run_turn(david, [(david, "tranquilos")], TurnContext()))

    prompt = llm.last_system_prompt
    assert "FORMATO DE SALIDA OBLIGATORIO" in prompt
    assert "TURNO BREVE" not in prompt
    assert llm.calls[-1]["quick_turn"] is False


def test_short_message_with_reply_to_someone_else_uses_full_contract():
    """Una respuesta reciente dirigida a otra persona desactiva el turno rápido."""
    state, _ = make_state()
    other = str(1001)
    history = [
        {"role": "user", "content": "hola", "author_id": other, "author_name": "Otro"},
        {
            "role": "assistant",
            "content": "¡Hola! ¿qué tal?",
            "reply_to_user_name": "Otro",
        },
    ] * ((QUICK_HISTORY_MESSAGES // 2) + 1)
    state.histories[0] = history
    llm = FakeLLM(replies=[llm_json("hola")])
    david = FakeUser(42, "David")
    svc = _service(llm, state)

    asyncio.run(svc.run_turn(david, [(david, "tranquilos")], TurnContext()))

    assert "TURNO BREVE" not in llm.last_system_prompt


def test_short_message_solo_channel_still_quick():
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "hola", "author_id": "42", "author_name": "David"},
        {"role": "assistant", "content": "¡Hey! ¿cómo vas?", "reply_to_user_name": "David"},
    ]
    llm = FakeLLM(replies=[llm_json("hola")])
    david = FakeUser(42, "David")
    svc = _service(llm, state)

    asyncio.run(svc.run_turn(david, [(david, "tranquilos")], TurnContext()))

    assert "TURNO BREVE" in llm.last_system_prompt


def test_prompt_forbids_repeating_recent_tics():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("vale")])
    david = FakeUser(42, "David")
    svc = _service(llm, state)

    asyncio.run(svc.run_turn(david, [(david, "buenos días")], TurnContext()))

    prompt = llm.last_system_prompt
    assert "PROHIBICIÓN DE BUCLE" in prompt
    assert "no repitas" in prompt
