"""Avisos de sistema renderizados como embeds."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from airi.adapters.discord_notifier import DiscordNotifier
from airi.discord_bot.embeds import (
    NOTICE_STYLES,
    connected_embed,
    disconnecting_embed,
    notice_embed,
)
from airi.discord_bot.turn import _reflect_and_publish
from airi.domain.notices import (
    discovery_notice,
    level_up_notice,
    meet_notice,
    memory_saved_notice,
    relationship_confirmed_notice,
    relationship_proposed_notice,
    self_changed_notice,
    web_search_notice,
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


@pytest.mark.parametrize(
    ("notice", "title_fragment"),
    [
        (meet_notice("Ana", user_id=1), "Nuevo encuentro"),
        (discovery_notice(user_id=1), "Descubrimiento"),
        (memory_saved_notice(user_id=1), "Memoria guardada"),
        (self_changed_notice(user_id=1), "Airi ha aprendido algo nuevo"),
        (level_up_notice("Ana", "Amiga", user_id=1), "Nivel de afinidad"),
        (relationship_proposed_notice("Ana", user_id=1), "Propuesta"),
        (relationship_confirmed_notice("Ana", user_id=1), "Pareja confirmada"),
        (web_search_notice(), "Buscando en la web"),
    ],
)
def test_notice_kind_has_its_own_title(notice, title_fragment):
    embed = notice_embed(notice)
    assert title_fragment in embed.title
    assert notice.kind in NOTICE_STYLES


def test_self_changed_notice_has_no_identity_command_hint():
    embed = notice_embed(self_changed_notice(user_id=1))
    assert "identidad-airi" not in embed.description


def test_post_turn_string_notice_keeps_generic_embed():
    embed = notice_embed("Airi recordará este evento")
    assert "Airi" in embed.title
    assert "recordará" in embed.description


def test_discord_notifier_sends_embeds():
    channel = FakeChannel()
    run(DiscordNotifier(channel).send(memory_saved_notice(user_id=1)))
    assert len(channel.sent) == 1
    embed = channel.sent[0][1]["embed"]
    assert "Memoria guardada" in embed.title
    assert "recordará" in embed.description


def test_reflection_publishes_discovery_and_self_change_embeds():
    channel = FakeChannel()

    async def reflect(uid, now):
        return SimpleNamespace(
            discovery="He descubierto que me gusta la lluvia.",
            self_entry={"key": "traits.curiosa"},
        )

    run(_reflect_and_publish(channel, 1, 1_000_000.0, reflect))

    titles = [kwargs["embed"].title for _args, kwargs in channel.sent]
    assert any("Descubrimiento" in title for title in titles)
    assert any("Airi ha aprendido algo nuevo" in title for title in titles)
