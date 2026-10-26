"""Flujo de corrección explícita de preferencia (R7.7 + R10)."""

from __future__ import annotations

import asyncio

from airi.domain import memories as domain_memories
from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeLLM, FakeUser, llm_json, make_state


def test_explicit_preference_correction_updates_prompt_and_memory():
    state, _ = make_state(now=1_000.0)
    domain_memories.add_memory(
        state.memories,
        1,
        "Le encanta el flan.",
        now=1_000.0,
        source_text="Mi postre favorito es el flan.",
    )
    llm = FakeLLM(default_reply=llm_json("Entendido."))
    service = ConversationService(llm=llm, state=state, clock=lambda: 1_000.0)
    user = FakeUser(1, "Ana")

    draft = asyncio.run(
        service.generate_turn(
            user,
            [(user, "No, me equivoqué: mi postre favorito es el tiramisú.")],
            TurnContext(now=1_000.0, allow_web=False),
        )
    )
    prompt = llm.last_system_prompt
    assert "=== CORRECCIÓN DE PREFERENCIA (PRIORIDAD) ===" in prompt
    assert "Su postre favorito es el tiramisú." in prompt
    assert "Le encanta el flan." in prompt

    service.apply_turn(draft)
    entries = domain_memories.user_memories(state.memories, 1)
    assert [e["status"] for e in entries] == [
        domain_memories.SUPERSEDED,
        domain_memories.ACTIVE,
    ]

    asyncio.run(
        service.generate_turn(
            user,
            [(user, "¿Qué postre crees que me gusta?")],
            TurnContext(now=1_010.0, allow_web=False),
        )
    )
    prompt = llm.last_system_prompt
    assert "Su postre favorito es el tiramisú." in prompt
    assert "Le encanta el flan." not in prompt
    assert "=== MEMORIA RELEVANTE ===" in prompt
