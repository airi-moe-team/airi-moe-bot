"""Generación sin efectos y aplicación síncrona (tarea 5.3)."""

from __future__ import annotations

import asyncio

from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeLLM, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")


def make_service(state, llm):
    return ConversationService(
        llm=llm,
        state=state,
        clock=lambda: NOW,
        date_delta_max=5,
    )


def run(coro):
    return asyncio.run(coro)


def test_generate_does_not_mutate_state():
    state, counters = make_state()
    llm = FakeLLM(
        replies=[
            llm_json(
                "¡Hola!",
                affinity_delta=2,
                affinity_event="me alegro de verte",
                memory="A David le gusta el ramen",
                diary="Hoy he hablado con David.",
            )
        ]
    )
    service = make_service(state, llm)

    draft = run(
        service.generate_turn(
            DAVID,
            [(DAVID, "hola, te traigo ramen")],
            TurnContext(channel_id=7),
        )
    )

    assert draft.answer == "¡Hola!"
    assert state.users == {}
    assert state.affinity == {}
    assert state.memories == {}
    assert state.diary == []
    assert state.histories == {}
    assert state.dates == {}
    assert counters == {
        "affinity": 0,
        "world": 0,
        "dates": 0,
        "memories": 0,
        "diary": 0,
        "users": 0,
        "diary_logs": [],
    }


def test_apply_then_persists_all_effects():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("¡Hola!", affinity_delta=2, affinity_event="alegría")])
    service = make_service(state, llm)

    draft = run(
        service.generate_turn(
            DAVID,
            [(DAVID, "hola")],
            TurnContext(channel_id=7),
        )
    )
    result = service.apply_turn(draft)

    assert result.reply == "¡Hola!"
    assert result.affinity_applied == 2
    assert state.users["42"]["name"] == "David"
    assert state.entry_points(42) == 2
    assert state.histories[7][-1]["role"] == "assistant"
    assert result.notices == []
