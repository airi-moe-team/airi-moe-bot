"""Avisos de sistema renderizados como embeds."""

from __future__ import annotations

import asyncio

from airi.adapters.discord_notifier import DiscordNotifier
from airi.discord_bot.embeds import (
    connected_embed,
    disconnecting_embed,
    notice_embed,
)


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


def run(coro):
    return asyncio.run(coro)


def test_connection_notice_is_an_embed():
    embed = connected_embed()
    assert "Airi se ha conectado" in embed.title
    assert "en línea" in embed.description


def test_disconnection_notice_includes_reason_in_embed():
    embed = disconnecting_embed("me voy a dormir")
    assert "desconectando" in embed.title
    assert "me voy a dormir" in embed.description


def test_post_turn_notice_is_an_embed():
    embed = notice_embed("Airi recordará este evento")
    assert "Airi" in embed.title
    assert "recordará" in embed.description


def test_discord_notifier_sends_embeds():
    channel = FakeChannel()
    run(DiscordNotifier(channel).send("Airi recordará este evento"))
    assert len(channel.sent) == 1
    embed = channel.sent[0][1]["embed"]
    assert "recordará" in embed.description
