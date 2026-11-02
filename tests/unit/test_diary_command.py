"""Privacidad y presentación del comando !diario."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from airi.discord_bot.commands import diary
from airi.domain.diary import new_diary_entry
from airi.testing import make_state

NOW = 1_000_000.0


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class FakeAuthor:
    def __init__(self, user_id):
        self.id = user_id
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class FakeMessage:
    def __init__(self, content, author_id, *, guild=object()):
        self.content = content
        self.author = FakeAuthor(author_id)
        self.channel = FakeChannel()
        self.guild = guild


def run(coro):
    return asyncio.run(coro)


def make_context():
    state, _ = make_state()
    state.diary.extend([
        new_diary_entry("gift", 1, "Ana", "A Ana le gustaron las flores.", NOW - 60),
        new_diary_entry("reflection", 2, "Beto", "Me sentí feliz con Beto.", NOW - 30),
    ])
    return SimpleNamespace(state=state, owner_id=99)


def test_public_command_shows_only_entries_about_the_invoker():
    ctx = make_context()
    message = FakeMessage("!diario", 1)

    run(diary.handle(ctx, message))

    description = message.channel.sent[0][1]["embed"].description
    assert "A Ana le gustaron las flores" in description
    assert "Beto" not in description


def test_only_owner_can_request_complete_diary_in_dm():
    ctx = make_context()
    message = FakeMessage("!diario todos", 99, guild=None)

    run(diary.handle(ctx, message))

    assert not message.channel.sent
    description = message.author.sent[0][1]["embed"].description
    assert "A Ana le gustaron las flores" in description
    assert "Me sentí feliz con Beto" in description
    assert "Regalo" in description
    assert "Reflexión de Airi" in description


def test_owner_cannot_publish_complete_diary_in_a_guild_channel():
    ctx = make_context()
    message = FakeMessage("!diario todos", 99)

    run(diary.handle(ctx, message))

    assert not message.author.sent
    description = message.channel.sent[0][1]["embed"].description
    assert "mensaje privado" in description.lower()
    assert "A Ana le gustaron las flores" not in description


def test_non_owner_cannot_request_complete_diary():
    ctx = make_context()
    message = FakeMessage("!diario todos", 1)

    run(diary.handle(ctx, message))

    description = message.channel.sent[0][1]["embed"].description
    assert "A Ana le gustaron las flores" in description
    assert "Beto" not in description
