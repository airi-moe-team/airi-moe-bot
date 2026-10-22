"""El turno incluye el motivo del último cierre hasta que se entrega una vez."""

from __future__ import annotations

import asyncio

from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeLLM, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")


def _service(llm, state):
    return ConversationService(
        llm=llm,
        state=state,
        clock=lambda: NOW,
        date_delta_max=5,
    )


def _shutdown(state, **overrides):
    entry = {
        "kind": "self",
        "reason": "me fui a dormir",
        "status": "confirmed",
    }
    entry.update(overrides)
    state.world["last_shutdown"] = entry


def test_prompt_contains_last_shutdown_reason():
    state, _ = make_state()
    _shutdown(state)
    llm = FakeLLM(replies=[llm_json("hola")])

    asyncio.run(
        _service(llm, state).run_turn(DAVID, [(DAVID, "hola")], TurnContext())
    )

    assert "=== TU ÚLTIMA DESCONEXIÓN ===" in llm.last_system_prompt
    assert "«me fui a dormir»" in llm.last_system_prompt


def test_prompt_omits_delivered_reason():
    state, _ = make_state()
    _shutdown(state, context_delivered=True)
    llm = FakeLLM(replies=[llm_json("hola")])

    asyncio.run(
        _service(llm, state).run_turn(DAVID, [(DAVID, "hola")], TurnContext())
    )

    assert "TU ÚLTIMA DESCONEXIÓN" not in llm.last_system_prompt
