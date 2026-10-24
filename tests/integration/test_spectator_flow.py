"""Tests de integración del flujo del modo espectador sin red ni Discord."""

import asyncio

from airi.services.conversation import ConversationService, TurnContext
from airi.services.passive_buffer import PassiveBuffer
from airi.services.spectator_policy import ActivitiesCooldown, evaluate_event
from airi.testing import FakeLLM, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")


def _simple_policy(**kw):
    from airi.domain.spectator import AiriSpectatorPolicy

    kw.setdefault("enabled", True)
    return AiriSpectatorPolicy(**kw)


def make_service(llm, state):
    return ConversationService(llm=llm, state=state, clock=lambda: NOW)


def run(coro):
    return asyncio.run(coro)


def _spectator_context(reason, snapshot):
    return TurnContext(
        channel_id=0,
        correlation_id="cid123",
        kind="spectator",
        now=NOW,
        spectator_reason=reason,
        spectator_snapshot=tuple(snapshot),
    )


def test_turno_espectador_inyecta_snapshot_en_prompt_sin_persistirlo():
    state, counters = make_state()
    llm = FakeLLM(replies=[llm_json("¡yo siempre tengo espacio para un buen ramen!", affinity_delta=0, stay_active=True)])
    svc = make_service(llm, state)

    snapshot = [
        {
            "author_id": "7",
            "author_name": "B",
            "content": "¿alguien quiere ramen?",
            "message_id": "m7",
        },
    ]
    result = run(svc.generate_turn(DAVID, [(DAVID, "¿alguien quiere ramen?")],
                                   _spectator_context("topic", snapshot)))

    ev = result.trace
    assert ev.spectator_reason == "topic"
    assert ev.spectator_snapshot == snapshot
    assert ev.spectator_probability_roll == 0.0
    # El historial real NO contiene la captura efímera; solo el turno real.
    assert not any(entry.get("spectator") for entry in result.history)
    # Evento serializable a traza/replay: de ida y vuelta conserva el snapshot.
    data = ev.to_dict()
    restored = type(ev).from_dict(data)
    assert restored.spectator_reason == "topic"
    assert restored.spectator_snapshot == snapshot


def test_turno_espectador_no_persiste_pasivos_al_aplicar():
    state, counters = make_state()
    llm = FakeLLM(replies=[llm_json("suena bien", affinity_delta=0, stay_active=True)])
    svc = make_service(llm, state)

    snapshot = [{"author_id": "7", "author_name": "B", "content": "mucho contexto", "message_id": "m1"}]
    ctx = _spectator_context("topic", snapshot)
    draft = run(svc.generate_turn(DAVID, [(DAVID, "otra cosa")], ctx))
    result = svc.apply_turn(draft)

    assert result.reply == "suena bien"
    persisted = state.histories.get(ctx.channel_id, [])
    contents = "\n".join(str(entry.get("content", "")) for entry in persisted)
    assert "otra cosa" in contents
    assert "mucho contexto" not in contents
    assert not any(entry.get("spectator") for entry in persisted)


def test_finalize_spectator_consume_snapshot_y_arma_cooldown():
    from airi.discord_bot.turn import _finalize_spectator_turn

    class Channel:
        id = 0

    class Author:
        id = 42

    class Ctx:
        pass

    buffer = PassiveBuffer(buffer_max=8, ttl_seconds=1000, clock=lambda: NOW)
    gate = ActivitiesCooldown(cooldown_seconds=300, clock=lambda: NOW)
    ctx = Ctx()
    ctx.passive_buffer = buffer
    ctx.spectator_gate = gate

    buffer.append("0", "7", "B", "tema previo", message_id="m1")
    buffer.append("0", "42", "David", "trigger", message_id="m2")

    snapshot = (
        {"author_id": "7", "author_name": "B", "content": "tema previo", "message_id": "m1"},
    )
    _finalize_spectator_turn(ctx, Channel(), Author(), "spectator", "topic", snapshot, False)

    remaining = buffer.snapshot("0", now=NOW)
    assert [e.message_id for e in remaining] == ["m2"]
    # El cooldown quedó armado al publicar con éxito.
    assert not gate.can_fire("0", "42", now=NOW)
    # Dentro del cooldown NO se repite una intervención espontánea.
    decision = evaluate_event(
        policy=_simple_policy(),
        gate=gate,
        channel_id="0",
        author_id="42",
        mention=False,
        topic=True,
        affinity=False,
    )
    assert not decision.proceed


def test_mention_garantizada_bypass_y_no_arma_cooldown():
    from airi.discord_bot.turn import _finalize_spectator_turn

    class Channel:
        id = 0

    class Author:
        id = 42

    class Ctx:
        pass

    gate = ActivitiesCooldown(cooldown_seconds=300, clock=lambda: NOW)
    ctx = Ctx()
    ctx.spectator_gate = gate
    buffer = PassiveBuffer(buffer_max=8, ttl_seconds=1000, clock=lambda: NOW)
    ctx.passive_buffer = buffer
    buffer.append("0", "9", "Z", "oh", message_id="m9")

    _finalize_spectator_turn(
        ctx, Channel(), Author(), "spectator", "mention", ({"message_id": "m9"},), True
    )
    assert gate.can_fire("0", "42", now=NOW)


def test_gate_y_tirada_fallida_no_consume_cooldown():
    rolls = iter([0.9, 0.1])
    gate = ActivitiesCooldown(cooldown_seconds=300, clock=lambda: NOW)
    gate.next_roll = lambda: next(rolls)

    primera = evaluate_event(
        policy=_simple_policy(), gate=gate, channel_id="0", author_id="42",
        mention=False, topic=True, affinity=False,
    )
    assert not primera.proceed
    assert gate.can_fire("0", "42", now=NOW)

    segunda = evaluate_event(
        policy=_simple_policy(), gate=gate, channel_id="0", author_id="42",
        mention=False, topic=True, affinity=False,
    )
    assert segunda.proceed
    assert segunda.reason == "topic"
    assert gate.can_fire("0", "42", now=NOW)  # solo se arma al publicar


def test_snapshot_vacio_igual_arma_cooldown():
    from airi.discord_bot.turn import _finalize_spectator_turn

    class Channel:
        id = 0

    class Author:
        id = 42

    class Ctx:
        pass

    gate = ActivitiesCooldown(cooldown_seconds=300, clock=lambda: NOW)
    ctx = Ctx()
    ctx.spectator_gate = gate
    _finalize_spectator_turn(ctx, Channel(), Author(), "spectator", "topic", (), False)
    assert not gate.can_fire("0", "42", now=NOW)


def test_cooldown_por_clave_independiente():
    gate = ActivitiesCooldown(cooldown_seconds=300, clock=lambda: NOW)
    gate.arm("canal-a", "42", now=NOW)
    assert gate.can_fire("canal-b", "42", now=NOW)
    assert gate.can_fire("canal-a", "999", now=NOW)
