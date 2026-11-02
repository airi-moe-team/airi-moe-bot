"""Reflexión introspectiva: descubrimiento y cambio de identidad."""

from __future__ import annotations

import asyncio

from airi.domain.prompts import self_model_prompt_section
from airi.services.self_service import SelfService
from airi.testing import FakeLLM, FakeUser, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")


def run(coro):
    return asyncio.run(coro)


def test_forced_reflection_adds_note_and_applies_guarded_change():
    state, counters = make_state(users={"42": {"name": "David", "interactions": 10}})
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
    before_prompt = self_model_prompt_section({"self": state.self_model()})
    before_curiosity = next(
        line for line in before_prompt.splitlines() if line.startswith("Curiosidad:")
    )

    outcome = run(service.reflect(DAVID, now=NOW, force=True))

    assert outcome.ran is True
    assert outcome.discovery
    assert outcome.self_entry is not None
    assert state.self_notes()[-1]["text"] == outcome.discovery
    assert state.self_model()["traits"]["curiosa"] == 5
    assert state.self_model()["history"][-1]["discovery_ref"] == outcome.discovery
    assert all(kind != "discovery" for kind, _uid, _text in counters["diary_logs"])
    after_prompt = self_model_prompt_section({"self": state.self_model()})
    after_curiosity = next(
        line for line in after_prompt.splitlines() if line.startswith("Curiosidad:")
    )
    assert after_curiosity != before_curiosity
    assert "(5/5)" in after_curiosity
    assert state.self_model()["last_reflection_at"] == NOW
    assert llm.calls[0]["reasoning_budget_tokens"] == 256


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


def test_reflection_prompt_contains_current_traits_and_private_recent_evidence_only():
    state, _ = make_state(users={"42": {"name": "David", "interactions": 10}})
    state.diary.extend([
        {"ts": NOW - 30, "user_id": "42", "kind": "memory", "text": "David habló de sus dibujos."},
        {"ts": NOW - 20, "user_id": "99", "kind": "memory", "text": "Secreto de otra persona."},
    ])
    state.add_self_note("Me gusta explorar ideas nuevas.", now=NOW - 10)
    llm = FakeLLM(replies=['{"discovery":"none","self_update":{"key":"none","op":"none",'
                           '"value":"","reason":"","evidence":""}}'])
    service = SelfService(llm=llm, state=state)

    run(service.reflect(DAVID, now=NOW, force=True))

    prompt = llm.calls[0]["messages"][1]["content"]
    assert "Mis rasgos (1-5)" in prompt
    assert "David habló de sus dibujos" in prompt
    assert "Me gusta explorar ideas nuevas" in prompt
    assert "Secreto de otra persona" not in prompt
    assert "evidencia concreta" in prompt.lower()
    assert "descubrimiento actúa como gatillo" in prompt.lower()
    assert "no uses el descubrimiento como única evidencia" in prompt.lower()
    assert "patrón estable:" in prompt.lower()
    assert "contextual:" in prompt.lower()
    assert "hipótesis:" in prompt.lower()
    assert "no incluyas nombres de usuarios" in prompt.lower()
    assert "no guardes frases vacías" in prompt.lower()
    assert "tampoco reformules" in prompt.lower()
    assert 'si discovery es "none"' in prompt.lower()


def test_discovery_without_stable_trait_pattern_does_not_force_trait_change():
    state, _ = make_state(users={"42": {"name": "David", "interactions": 10}})
    llm = FakeLLM(
        replies=[
            '{"discovery":"Hoy me apetecía probar una bebida nueva.",'
            '"self_update":{"key":"none","op":"none","value":"",'
            '"reason":"","evidence":""}}'
        ]
    )
    service = SelfService(llm=llm, state=state, clock=lambda: NOW)
    before = dict(state.self_model()["traits"])

    outcome = run(service.reflect(DAVID, now=NOW, force=True))

    assert outcome.discovery == "Hoy me apetecía probar una bebida nueva."
    assert outcome.self_entry is None
    assert state.self_model()["traits"] == before


def test_generic_discovery_is_not_saved_or_published_as_a_change():
    state, _ = make_state(users={"42": {"name": "David", "interactions": 10}})
    llm = FakeLLM(replies=[
        '{"discovery":"Hipótesis: Me estoy descubriendo poco a poco.",'
        '"self_update":{"key":"none","op":"none","value":"",'
        '"reason":"","evidence":""}}'
    ])
    service = SelfService(llm=llm, state=state, clock=lambda: NOW)

    outcome = run(service.reflect(DAVID, now=NOW, force=True))

    assert outcome.ran is True
    assert outcome.discovery is None
    assert outcome.changed is False
    assert state.self_notes() == []



def test_invalid_reflection_json_does_not_consume_reflection_clock():
    state, _ = make_state(users={"42": {"name": "David", "interactions": 10}})
    llm = FakeLLM(replies=["esto no es JSON"])
    service = SelfService(llm=llm, state=state)

    outcome = run(service.reflect(DAVID, now=NOW, force=True))

    assert outcome.ran is False
    assert state.self_model()["last_reflection_at"] == 0.0
