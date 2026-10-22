"""La decisión de marcharse llega al resultado del turno."""

from __future__ import annotations

import asyncio

from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeLLM, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")


def make_service(llm, state):
    return ConversationService(
        llm=llm,
        state=state,
        notifier=None,
        clock=lambda: NOW,
        date_delta_max=5,
    )


def run(coro):
    return asyncio.run(coro)


def test_disconnect_reason_reaches_the_turn_result():
    state, _ = make_state()
    llm = FakeLLM(
        replies=[
            llm_json(
                "Buenas noches, me voy a dormir.",
                disconnect={"leave": True, "reason": "me voy a dormir"},
            )
        ]
    )
    result = run(
        make_service(llm, state).run_turn(
            DAVID, [(DAVID, "vamos a dormir")], TurnContext()
        )
    )
    assert result.disconnect_reason == "me voy a dormir"


def test_disconnect_is_ignored_without_reason():
    state, _ = make_state()
    llm = FakeLLM(
        replies=[
            llm_json(
                "Buenas noches.",
                disconnect={"leave": True, "reason": ""},
            )
        ]
    )
    result = run(
        make_service(llm, state).run_turn(
            DAVID, [(DAVID, "hasta mañana")], TurnContext()
        )
    )
    assert result.disconnect_reason is None


def test_incoherent_departure_is_repaired_once():
    state, _ = make_state()
    llm = FakeLLM(
        replies=[
            llm_json("Me voy a dormir.", disconnect={"leave": False, "reason": ""}),
            llm_json(
                "Buenas noches, me voy a dormir.",
                disconnect={"leave": True, "reason": "me voy a dormir"},
            ),
        ]
    )
    result = run(
        make_service(llm, state).run_turn(
            DAVID, [(DAVID, "vamos a dormir")], TurnContext()
        )
    )
    assert result.disconnect_reason == "me voy a dormir"
    assert len(llm.calls) == 2
