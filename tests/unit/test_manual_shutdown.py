"""El Ctrl+C envía aviso de desconexión y deja el motivo para el próximo prompt."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

import discord

from airi.discord_bot import client as client_module
from airi.services.state import AppState


class FakePersistence:
    def __init__(self):
        self.commits = 0

    @contextmanager
    def transaction(self):
        try:
            yield
        except Exception:
            raise
        else:
            self.commits += 1


class FakeClient:
    user = "airi"
    instances = []

    def __init__(self, *, intents):
        self.events = {}
        self.closed = False
        self._channel = None
        FakeClient.instances.append(self)

    def event(self, fn):
        self.events[fn.__name__] = fn
        return fn

    async def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed

    def get_channel(self, _id):
        return self._channel


class FakeChannel:
    id = 7

    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return None


def _setup(monkeypatch, *, manual_shutdown):
    monkeypatch.setattr(client_module.discord, "Client", FakeClient)
    FakeClient.instances.clear()
    channel = FakeChannel()

    def build_ctx(_ch, pending_message_tracker=None):
        from airi.discord_bot.context import BotContext
        from airi.services.state import AppState

        return BotContext(channel_id=7, state=AppState())

    client = client_module.create_client(
        build_ctx=build_ctx,
        registry=type("R", (), {"match": lambda self, _c: None})(),
        channel_id=7,
        manual_shutdown=manual_shutdown,
    )
    client._channel = channel
    return client, channel


def _run_on_ready(client):
    async def scenario():
        await client.events["on_ready"]()

    asyncio.run(scenario())
    return getattr(client, "manual_shutdown_trigger", None)


def _trigger_and_settle(client, trigger):
    async def scenario():
        trigger()
        await asyncio.sleep(0.2)

    asyncio.run(scenario())
    return client


def _disconnect_count(channel):
    return sum(
        1
        for (_args, kwargs) in channel.sent
        if getattr(kwargs.get("embed"), "title", "") == "🚪 Airi se está desconectando"
    )


def _connected_count(channel):
    return sum(
        1
        for (_args, kwargs) in channel.sent
        if getattr(kwargs.get("embed"), "title", "") == "🟢 Airi se ha conectado"
    )


def test_ctrl_c_sends_disconnect_embed_and_saves_reason(monkeypatch):
    state = AppState()
    persistence = FakePersistence()
    client, channel = _setup(
        monkeypatch,
        manual_shutdown={
            "state": state,
            "persistence": persistence,
            "reason": "se fue a dormir",
        },
    )

    trigger = _run_on_ready(client)
    _trigger_and_settle(client, trigger)

    assert client.closed is True
    assert _connected_count(channel) == 1
    assert _disconnect_count(channel) == 1
    (_args, _kwargs), *rest = (
        item for item in channel.sent
        if getattr(item[1].get("embed"), "title", "")
        == "🚪 Airi se está desconectando"
    )
    assert _args == ()
    embed = _kwargs["embed"]
    assert isinstance(embed, discord.Embed)
    assert "se fue a dormir" in embed.description

    entry = state.world["last_shutdown"]
    assert entry["kind"] == "self"
    assert entry["reason"] == "se fue a dormir"
    assert entry["status"] == "confirmed"
    assert entry["origin"] == "manual"
    assert entry["correlation_id"] == ""
    assert entry["requested_at"] > 0
    assert entry["updated_at"] >= entry["requested_at"]
    assert entry["context_delivered"] is False
    assert persistence.commits >= 1


def test_manual_entry_feeds_reconnect_prompt(monkeypatch):
    state = AppState()
    client, channel = _setup(
        monkeypatch,
        manual_shutdown={"state": state, "persistence": None, "reason": "zzz"},
    )

    trigger = _run_on_ready(client)
    _trigger_and_settle(client, trigger)

    from airi.domain.prompts import last_shutdown_prompt_section

    section = last_shutdown_prompt_section(state.world)
    assert "«zzz»" in section


def test_repeated_ctrl_c_is_ignored(monkeypatch):
    state = AppState()
    client, channel = _setup(
        monkeypatch,
        manual_shutdown={"state": state, "persistence": None, "reason": "zzz"},
    )

    trigger = _run_on_ready(client)

    async def scenario():
        trigger()
        trigger()  # duplicado mientras el cierre está en curso
        await asyncio.sleep(0.2)
        trigger()  # después de cerrar
        await asyncio.sleep(0.1)

    asyncio.run(scenario())

    assert client.closed is True
    assert _disconnect_count(channel) == 1


def test_without_manual_shutdown_no_hook_is_installed(monkeypatch):
    client, _channel = _setup(monkeypatch, manual_shutdown=None)
    trigger = _run_on_ready(client)
    assert trigger is None
