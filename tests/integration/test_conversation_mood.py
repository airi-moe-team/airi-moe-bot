"""Integración del ánimo transitorio en el turno."""

from __future__ import annotations

import asyncio

from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeLLM, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")

MOOD = {
    "label": "juguetona",
    "valence": 2,
    "energy": 4,
    "warmth": 3,
    "cause": "broma compartida",
}


def make_service(llm, state):
    return ConversationService(
        llm=llm,
        state=state,
        clock=lambda: NOW,
        date_delta_max=5,
    )


def run(coro):
    return asyncio.run(coro)


def test_prompt_includes_mood_section():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("hola")])
    run(make_service(llm, state).run_turn(DAVID, [(DAVID, "hola")], TurnContext()))
    assert "=== ÁNIMO DE ESTE TURNO ===" in llm.last_system_prompt
    assert "Con David" in llm.last_system_prompt


def test_turn_persists_declared_mood_and_result():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("¡qué gracioso!", mood=MOOD)])
    result = run(
        make_service(llm, state).run_turn(
            DAVID, [(DAVID, "te cuento un chiste")], TurnContext(channel_id=7)
        )
    )
    assert result.mood_source == "model"
    assert result.mood["label"] == "juguetona"
    assert state.world["mood"]["label"] == "juguetona"
    assert state.world["mood"]["cause"] == "broma compartida"
    assert len(state.world["mood_history"]) == 1
    assert state.world["mood_history"][0]["user_id"] == "42"
    assert result.trace.mood["label"] == "juguetona"
    assert result.trace.mood_source == "model"


def test_turn_falls_back_to_deterministic_mood_when_missing():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("hola")])
    result = run(
        make_service(llm, state).run_turn(
            DAVID, [(DAVID, "hola")], TurnContext(channel_id=7)
        )
    )
    assert result.mood_source == "fallback"
    assert result.mood is not None
    assert state.world["mood"]["label"] == result.mood["label"]


def test_mood_does_not_change_traits():
    state, _ = make_state()
    before = dict(state.self_model()["traits"])
    llm = FakeLLM(replies=[llm_json("hola", mood=MOOD)])
    run(make_service(llm, state).run_turn(DAVID, [(DAVID, "hola")], TurnContext()))
    assert state.self_model()["traits"] == before


def test_next_turn_prompt_reads_previous_mood():
    state, _ = make_state()
    llm = FakeLLM(
        replies=[llm_json("primero", mood=MOOD), llm_json("segundo")]
    )
    service = make_service(llm, state)
    run(service.run_turn(DAVID, [(DAVID, "hola")], TurnContext(channel_id=7)))
    run(service.run_turn(DAVID, [(DAVID, "sigo aquí")], TurnContext(channel_id=7)))
    assert "juguetona" in llm.last_system_prompt
    assert "broma compartida" in llm.last_system_prompt


def test_other_user_does_not_see_the_mood_cause():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("primero", mood=MOOD)])
    service = make_service(llm, state)
    run(service.run_turn(DAVID, [(DAVID, "hola")], TurnContext(channel_id=7)))

    other = FakeUser(99, "Ana")
    llm.replies = [llm_json("hola Ana")]
    run(service.run_turn(other, [(other, "hola")], TurnContext(channel_id=7)))
    prompt = llm.last_system_prompt
    assert "juguetona" in prompt
    assert "broma compartida" not in prompt
    assert "Con Ana" in prompt


def test_mood_is_still_recorded_in_proactive_turns():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("hola", mood=str("curiosa"))])
    result = run(
        make_service(llm, state).run_turn(
            DAVID,
            [(DAVID, "hola")],
            TurnContext(channel_id=7, kind="proactive"),
        )
    )
    assert result.mood["label"] == "curiosa"
    assert state.world["mood"]["label"] == "curiosa"
