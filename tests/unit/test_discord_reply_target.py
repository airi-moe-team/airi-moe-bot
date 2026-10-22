"""Las respuestas de Airi se vinculan al mensaje que las originó."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from airi.discord_bot.turn import _publish_result, send_long_message
from airi.services.state import AppState


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class FakeAuthor:
    id = 42


def run(coro):
    return asyncio.run(coro)


def test_long_message_references_original_only_on_first_chunk():
    channel = FakeChannel()
    message = object()
    content = "x" * 2100

    run(send_long_message(channel, content, reference=message))

    assert len(channel.sent) == 2
    assert channel.sent[0][1]["reference"] is message
    assert channel.sent[0][1]["mention_author"] is False
    assert "reference" not in channel.sent[1][1]
    assert "mention_author" not in channel.sent[1][1]


def test_normal_reply_references_the_user_message_without_mentioning_them():
    channel = FakeChannel()
    message = object()
    ctx = SimpleNamespace(state=AppState(dates={}), affinity_footer=lambda _user: "")
    result = SimpleNamespace(
        reply="Hola, te respondo a ti.",
        in_date=False,
        gif="none",
        gif_bytes=None,
        notices=[],
    )

    run(_publish_result(ctx, channel, FakeAuthor(), result, reply_target=message))

    assert channel.sent[0][0] == "Hola, te respondo a ti."
    assert channel.sent[0][1]["reference"] is message
    assert channel.sent[0][1]["mention_author"] is False


def test_reply_without_target_keeps_plain_channel_send():
    channel = FakeChannel()
    ctx = SimpleNamespace(state=AppState(dates={}), affinity_footer=lambda _user: "")
    result = SimpleNamespace(
        reply="Respuesta sin mensaje de origen.",
        in_date=False,
        gif="none",
        gif_bytes=None,
        notices=[],
    )

    run(_publish_result(ctx, channel, FakeAuthor(), result))

    assert channel.sent == [("Respuesta sin mensaje de origen.", {})]
