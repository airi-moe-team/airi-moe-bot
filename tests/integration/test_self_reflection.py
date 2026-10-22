"""Reflexión introspectiva: descubrimiento y cambio de identidad."""

from __future__ import annotations

import asyncio

from airi.services.self_service import SelfService
from airi.testing import FakeLLM, FakeUser, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")


def run(coro):
    return asyncio.run(coro)


def test_forced_reflection_adds_note_and_applies_guarded_change():
    state, _ = make_state(users={"42": {"name": "David", "interactions": 10}})
    llm = FakeLLM(
        replies=[
            """{
                "discovery": "Me he dado cuenta de que me gusta escuchar historias.",
                "self_update": {
                    "key": "traits.curiosa",
                    "op": "inc",
                    "value": "1",
                    "reason": "sus historias me intrigan",
                    "evidence": "me contó algo nuevo"
                }
            }"""
        ]
    )
    service = SelfService(llm=llm, state=state, clock=lambda: NOW)

    outcome = run(service.reflect(DAVID, now=NOW, force=True))

    assert outcome.ran is True
    assert outcome.discovery
    assert outcome.self_entry is not None
    assert state.self_notes()[-1]["text"] == outcome.discovery
    assert state.self_model()["traits"]["curiosa"] == 5
    assert state.self_model()["last_reflection_at"] == NOW


def test_reflection_is_skipped_when_not_due():
    state, _ = make_state(users={"42": {"name": "David", "interactions": 3}})
    llm = FakeLLM(replies=['{"discovery":"none","self_update":{"key":"none","op":"none","value":"","reason":"","evidence":""}}'])
    service = SelfService(llm=llm, state=state, clock=lambda: NOW)

    outcome = run(service.reflect(DAVID, now=NOW))

    assert outcome.ran is False
    assert llm.calls == []


def test_reflection_without_changes_still_marks_the_clock():
    state, _ = make_state(users={"42": {"name": "David", "interactions": 10}})
    llm = FakeLLM(
        replies=[
            '{"discovery":"none","self_update":{"key":"none","op":"none",'
            '"value":"","reason":"","evidence":""}}'
        ]
    )
    service = SelfService(llm=llm, state=state, clock=lambda: NOW)

    outcome = run(service.reflect(DAVID, now=NOW, force=True))

    assert outcome.ran is True
    assert outcome.changed is False
    assert state.self_model()["last_reflection_at"] == NOW
