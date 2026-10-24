"""Pruebas de inyección del modo de conversación en el prompt."""

from __future__ import annotations

import asyncio

import pytest

from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeGif, FakeLLM, FakeNotifier, FakeSearch, FakeUser, llm_json, make_state


def run(coro):
    return asyncio.run(coro)


def test_prompt_incluye_seccion_modo_activo():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("hola", affinity_delta=0)])
    svc = ConversationService(
        llm=llm,
        state=state,
        search=FakeSearch(),
        gifs=FakeGif(),
        notifier=FakeNotifier(),
        clock=lambda: 1_000_000.0,
    )
    user = FakeUser(42, "David")
    ctx = TurnContext(conversation_mode="active", conversation_reason="tema ramen")
    run(svc.run_turn(user, [(user, "hola")], ctx))
    system = llm.calls[0]["messages"][0]["content"]
    assert "CONVERSACIÓN ACTIVA" in system
    assert "tema ramen" not in system  # el motivo no se inyecta en activo por defecto
    assert "reply=\"\"" in system or 'reply=""' in system


def test_prompt_incluye_seccion_modo_espectador_con_motivo():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("hola", affinity_delta=0)])
    svc = ConversationService(
        llm=llm,
        state=state,
        search=FakeSearch(),
        gifs=FakeGif(),
        notifier=FakeNotifier(),
        clock=lambda: 1_000_000.0,
    )
    user = FakeUser(42, "David")
    ctx = TurnContext(conversation_mode="spectator", conversation_reason="topic")
    run(svc.run_turn(user, [(user, "hola")], ctx))
    system = llm.calls[0]["messages"][0]["content"]
    assert "MODO ESPECTADOR (DESPERTAR)" in system
    assert "Motivo de activación: topic" in system


def test_prompt_modo_normal_no_inyecta_seccion():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("hola", affinity_delta=0)])
    svc = ConversationService(
        llm=llm,
        state=state,
        search=FakeSearch(),
        gifs=FakeGif(),
        notifier=FakeNotifier(),
        clock=lambda: 1_000_000.0,
    )
    user = FakeUser(42, "David")
    run(svc.run_turn(user, [(user, "hola")], TurnContext()))
    system = llm.calls[0]["messages"][0]["content"]
    assert "CONVERSACIÓN ACTIVA" not in system
    assert "MODO ESPECTADOR (DESPERTAR)" not in system
    assert "INICIATIVA PROACTIVA" not in system
