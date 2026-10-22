"""Los regalos no coronan pareja por alcanzar el umbral de afinidad."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from airi.discord_bot.commands import gifts
from airi.testing import FakeUser, make_state

NOW = 1_000_000.0


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)


class FakeMessage:
    def __init__(self, author, content, channel):
        self.author = author
        self.content = content
        self.channel = channel
        self.replies = []

    async def reply(self, content=None, **kwargs):
        self.replies.append(content)


def test_a_gift_crossing_the_affinity_threshold_does_not_crown_a_partner():
    state, _ = make_state(now=NOW)
    state.affinity_entry(42)["points"] = 99
    crowned = []

    async def judge_gift(session, item, user, recent):
        return ("Gracias~", 5, "me ha gustado el detalle")

    async def settle_relationship(*args, **kwargs):
        crowned.append((args, kwargs))

    ctx = SimpleNamespace(
        state=state,
        busy_date_owner=lambda exclude_id=None: (None, None),
        notify_busy=lambda *a, **k: None,
        judge_gift=judge_gift,
        settle_relationship=settle_relationship,
        request_timeout=5,
        persistence=None,
        commit_lock=None,
        log_diary_event=state.log_diary_event,
    )
    user = FakeUser(42, "Ana")
    message = FakeMessage(user, "!regalo flores", FakeChannel())

    asyncio.run(gifts.handle(ctx, message))

    assert state.entry_points(42) >= 100
    assert state.world["winner_id"] is None
    assert crowned == []
