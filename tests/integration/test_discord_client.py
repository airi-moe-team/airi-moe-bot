"""Tests del gate de canales del Discord client (`create_client`)."""

import asyncio
from types import SimpleNamespace

from airi.discord_bot import turn as turn_module
from airi.discord_bot.client import create_client, normalize_channel_ids


class FakeAuthor:
    def __init__(self, user_id, bot=False):
        self.id = user_id
        self.bot = bot
        self.display_name = f"User{user_id}"


class FakeChannel:
    def __init__(self, channel_id=7):
        self.id = channel_id
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)


class FakeMessage:
    def __init__(self, content, author, channel):
        self.content = content
        self.author = author
        self.channel = channel
        self.replies = []

    async def reply(self, content=None, **kwargs):
        self.replies.append(content)


def run(coro):
    return asyncio.run(coro)


def make_client(monkeypatch, allowed_ids):
    turn_calls = []

    async def fake_run_user_turn(ctx, channel, author, messages, reply_target=None):
        turn_calls.append((ctx, channel, author))

    monkeypatch.setattr(turn_module, "run_user_turn", fake_run_user_turn)

    def make_ctx(channel):
        async def expire_stale_dates_summarizing(channel_id, now=None):
            return []

        return SimpleNamespace(
            channel_id=channel.id,
            expire_stale_dates=lambda: False,
            expire_stale_dates_summarizing=expire_stale_dates_summarizing,
            expire_stale_questions=lambda: None,
            expire_scene_requests=lambda: [],
            pending_scene=lambda uid: False,
            state=SimpleNamespace(dates={}),
            busy_date_owner=lambda exclude_id: (None, None),
            debounce_seconds=0,
        )

    client = create_client(
        build_ctx=make_ctx,
        registry=SimpleNamespace(match=lambda content: None),
        channel_ids=allowed_ids,
    )
    return client, turn_calls


def test_on_message_ignores_disallowed_channel(monkeypatch):
    client, turn_calls = make_client(monkeypatch, allowed_ids={111})
    msg = FakeMessage("hola", FakeAuthor(42), FakeChannel(222))

    run(client.on_message(msg))

    assert turn_calls == []


def test_on_message_accepts_message_from_any_allowed_channel(monkeypatch):
    client, turn_calls = make_client(monkeypatch, allowed_ids={111, 222})
    msg = FakeMessage("hola", FakeAuthor(42), FakeChannel(222))

    run(client.on_message(msg))

    assert len(turn_calls) == 1
    assert turn_calls[0][0].channel_id == 222


def test_normalize_channel_ids_accepts_int_iterable_and_empty():
    assert normalize_channel_ids(111) == {111}
    assert normalize_channel_ids([111, 222]) == {111, 222}
    assert normalize_channel_ids({111, 222}) == {111, 222}
    assert normalize_channel_ids(None) == set()
    assert normalize_channel_ids(()) == set()


def test_create_client_still_accepts_a_single_int(monkeypatch):
    client, turn_calls = make_client(monkeypatch, allowed_ids=111)

    run(client.on_message(FakeMessage("hola", FakeAuthor(42), FakeChannel(111))))
    run(client.on_message(FakeMessage("hola", FakeAuthor(42), FakeChannel(999))))

    assert len(turn_calls) == 1
    assert turn_calls[0][0].channel_id == 111
