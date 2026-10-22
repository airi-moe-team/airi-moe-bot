"""Comandos !yo / !identidad-airi."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from airi.discord_bot.commands import identity
from airi.testing import make_state


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class FakeMessage:
    def __init__(self, content, author_id=1):
        self.content = content
        self.author = SimpleNamespace(id=author_id)
        self.channel = FakeChannel()
        self.replies = []

    async def reply(self, *args, **kwargs):
        self.replies.append((args, kwargs))


def run(coro):
    return asyncio.run(coro)


def make_ctx(owner_id=1):
    state, _ = make_state()
    return SimpleNamespace(state=state, owner_id=owner_id)


def test_yo_shows_current_identity_embed():
    ctx = make_ctx()
    message = FakeMessage("!yo")
    run(identity.handle_yo(ctx, message))
    assert message.channel.sent
    embed = message.channel.sent[0][1]["embed"]
    assert "Mis rasgos" in embed.description


def test_yo_does_not_show_private_notes():
    ctx = make_ctx()
    ctx.state.self_model()
    ctx.state.add_self_note(
        "La confianza que comparto con KOKODA me hace crecer", now=10.0
    )
    message = FakeMessage("!yo")
    run(identity.handle_yo(ctx, message))
    embed = message.channel.sent[0][1]["embed"]
    assert "KOKODA" not in embed.description
    assert "Mis rasgos" in embed.description


def test_yo_historia_without_changes():
    ctx = make_ctx()
    message = FakeMessage("!yo historia")
    run(identity.handle_yo_historia(ctx, message))
    embed = message.channel.sent[0][1]["embed"]
    assert "no ha cambiado nada" in embed.description


def test_yo_revertir_requires_owner():
    ctx = make_ctx(owner_id=1)
    message = FakeMessage("!yo revertir 1", author_id=999)
    run(identity.handle_yo_revertir(ctx, message))
    assert message.replies
    assert "Solo el dueño" in message.replies[0][1]["embed"].description


def test_yo_revertir_invalid_index():
    ctx = make_ctx()
    message = FakeMessage("!yo revertir 99")
    run(identity.handle_yo_revertir(ctx, message))
    assert message.replies
    assert "No encontré" in message.replies[0][1]["embed"].description
