"""Generación sin efectos y aplicación síncrona (tarea 5.3)."""

from __future__ import annotations

import asyncio

from airi.domain.time_perception import TimeConfig
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
    assert [notice.kind for notice in result.notices] == ["meet"]


def test_temporal_prompt_and_history_view_receive_fixed_turn_time():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("¡Hola!")])
    service = ConversationService(
        llm=llm,
        state=state,
        clock=lambda: NOW,
        time_config=TimeConfig(enabled=True, timezone="UTC"),
    )
    draft = run(service.generate_turn(
        DAVID, [(DAVID, "hola")], TurnContext(channel_id=7)
    ))
    prompt = llm.last_system_prompt
    user_message = llm.calls[0]["messages"][-1]["content"]
    assert "=== TU PERCEPCIÓN DEL TIEMPO ===" in prompt
    assert "No recites la hora" in prompt
    assert user_message.startswith("[ahora] [speaker=David|")
    assert draft.trace.time_context["enabled"] is True
    assert draft.trace.time_context["local_iso"] == "1970-01-12T13:46"
    assert "content" not in draft.trace.time_context
    result = service.apply_turn(draft)
    assert all(entry["ts"] == NOW for entry in result.history)
    assert state.histories[7][-1]["ts"] == NOW


def test_time_context_off_removes_temporal_prompt_and_tags():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("¡Hola!")])
    service = ConversationService(
        llm=llm,
        state=state,
        clock=lambda: NOW,
        time_config=TimeConfig(enabled=False),
    )
    run(service.generate_turn(
        DAVID, [(DAVID, "hola")], TurnContext(channel_id=7)
    ))
    prompt = llm.last_system_prompt
    user_message = llm.calls[0]["messages"][-1]["content"]
    assert "TU PERCEPCIÓN DEL TIEMPO" not in prompt
    assert user_message.startswith("[speaker=David|")
