"""La nota de variedad solo aparece cuando Airi acaba de cerrar con pregunta.

Evita el patrón visto en la traza 446b2a20a67e (todas las respuestas cerraban
preguntando) sin añadir reglas permanentes al prompt.
"""

from __future__ import annotations

import asyncio

from airi.domain.prompts import question_variety_nudge_section
from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeLLM, FakeUser, llm_json, make_state


def _service(llm, state):
    return ConversationService(llm=llm, state=state, clock=lambda: 1_000_000.0)


def _assistant_json(text):
    return {
        "role": "assistant",
        "content": llm_json(text),
        "reply_to_user_name": "David",
    }


def test_nudge_returns_empty_when_last_reply_does_not_end_in_question():
    history = [
        {"role": "user", "content": "hola"},
        _assistant_json("¡Hola! Qué gusto verte."),
    ]
    assert question_variety_nudge_section(history) == ""


def test_nudge_returns_empty_without_assistant_replies():
    assert question_variety_nudge_section([]) == ""
    assert question_variety_nudge_section(None) == ""


def test_nudge_extracts_reply_from_raw_json_history():
    history = [
        {"role": "user", "content": "hola"},
        _assistant_json("¿Y tú qué tal estás?"),
    ]
    section = question_variety_nudge_section(history)
    assert "NOTA DE VARIEDAD" in section
    assert "NO cierres con una pregunta" in section


def _run_turn(state, llm, message):
    david = FakeUser(42, "David")
    svc = _service(llm, state)
    asyncio.run(svc.run_turn(david, [(david, message)], TurnContext()))


def test_turn_after_question_closing_includes_nudge():
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "hola", "author_id": "42", "author_name": "David"},
        _assistant_json("¿Qué te trae por aquí?"),
    ]
    llm = FakeLLM(replies=[llm_json("¡Hola de nuevo!")])

    _run_turn(state, llm, "nada, curioseando")

    assert "NOTA DE VARIEDAD" in llm.last_system_prompt


def test_turn_after_statement_closing_has_no_nudge():
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "hola", "author_id": "42", "author_name": "David"},
        _assistant_json("¡Hola! Qué gusto verte otra vez."),
    ]
    llm = FakeLLM(replies=[llm_json("¡Hola!")])

    _run_turn(state, llm, "hola")

    prompt = llm.last_system_prompt
    assert "NOTA DE VARIEDAD" not in prompt
    assert "TU ÚLTIMA DESCONEXIÓN" not in prompt
