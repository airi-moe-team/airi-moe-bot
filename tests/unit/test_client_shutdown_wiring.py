"""El contexto de Discord conecta request_shutdown con el cierre del cliente."""

from __future__ import annotations

import asyncio

from airi.discord_bot import client as client_module
from airi.discord_bot.context import BotContext
from airi.services.state import AppState


class FakeClient:
    instances = []

    def __init__(self, *, intents):
        self.events = {}
        self.closed = False
        FakeClient.instances.append(self)

    def event(self, fn):
        self.events[fn.__name__] = fn
        return fn

    async def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed


class FakeChannel:
    id = 7

    async def send(self, *args, **kwargs):
        return None


class FakeMessage:
    def __init__(self, content):
        self.content = content
        self.channel = FakeChannel()
        self.author = type("Author", (), {"id": 42, "bot": False})()


class Registry:
    def match(self, _content):
        async def handler(ctx, _message):
            await ctx.request_shutdown(
                "me voy a dormir",
                user_id=42,
                correlation_id="cid-shutdown",
            )

        return handler


class FakePersistence:
    def __init__(self):
        self.commits = 0

    def transaction(self):
        from contextlib import contextmanager

        @contextmanager
        def _tx():
            try:
                yield
            finally:
                self.commits += 1

        return _tx()


def test_request_shutdown_closes_the_global_client(monkeypatch):
    monkeypatch.setattr(client_module.discord, "Client", FakeClient)
    FakeClient.instances.clear()

    def build_ctx(_channel, pending_message_tracker=None):
        return BotContext(
            channel_id=7,
            state=AppState(),
            expire_stale_dates=lambda: False,
        )

    async def scenario():
        client = client_module.create_client(
            build_ctx=build_ctx,
            registry=Registry(),
            channel_id=7,
        )
        await client.events["on_message"](FakeMessage("vamos a dormir"))
        await asyncio.sleep(0.7)
        return client

    client = asyncio.run(scenario())
    assert client.closed is True


def test_request_shutdown_records_origin_time_and_correlation(monkeypatch):
    monkeypatch.setattr(client_module.discord, "Client", FakeClient)
    FakeClient.instances.clear()
    state = AppState()
    persistence = FakePersistence()

    def build_ctx(_channel, pending_message_tracker=None):
        return BotContext(
            channel_id=7,
            state=state,
            persistence=persistence,
            expire_stale_dates=lambda: False,
        )

    async def scenario():
        client = client_module.create_client(
            build_ctx=build_ctx,
            registry=Registry(),
            channel_id=7,
        )
        await client.events["on_message"](FakeMessage("vamos a dormir"))
        await asyncio.sleep(0.7)
        return client

    client = asyncio.run(scenario())
    entry = state.world["last_shutdown"]
    assert client.closed is True
    assert entry["kind"] == "self"
    assert entry["reason"] == "me voy a dormir"
    assert entry["origin"] == "model"
    assert entry["correlation_id"] == "cid-shutdown"
    assert entry["status"] == "confirmed"
    assert entry["requested_at"] > 0
    assert entry["updated_at"] >= entry["requested_at"]
    assert entry["context_delivered"] is False
    assert persistence.commits >= 2
