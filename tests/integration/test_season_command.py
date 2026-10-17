"""Tests del comando !reiniciar-temporada (solo OWNER_ID)."""

import asyncio
from types import SimpleNamespace

from airi.discord_bot.commands import season
from airi.testing import make_state


class FakeAuthor:
    def __init__(self, user_id):
        self.id = user_id


class FakeChannel:
    def __init__(self, channel_id=7):
        self.id = channel_id
        self.sent = []

    async def send(self, content=None, **kwargs):
        if content is None and kwargs.get("embed") is not None:
            content = kwargs["embed"].description
        self.sent.append(content)


class FakeMessage:
    def __init__(self, author, channel):
        self.author = author
        self.channel = channel
        self.replies = []

    async def reply(self, content=None, **kwargs):
        if content is None and kwargs.get("embed") is not None:
            content = kwargs["embed"].description
        self.replies.append(content)


def run(coro):
    return asyncio.run(coro)


def _ctx(state, owner_id=1):
    return SimpleNamespace(owner_id=owner_id, state=state)


def _dirty_state():
    state, counters = make_state(
        affinity={
            "1": {"points": 72, "milestones": ["primer beso"]},
            "2": {"points": 30, "milestones": []},
        },
        dates={"1": {"state": "active", "scene": "cena"}},
        memories={"1": [{"text": "Le gusta el ramen", "created_at": 1.0}]},
        diary=[{"text": "Un día bonito", "created_at": 1.0}],
        users={
            "1": {
                "name": "David",
                "first_seen": 10.0,
                "last_seen": 20.0,
                "interactions": 72,
            },
            "2": {
                "name": "Joako",
                "first_seen": 11.0,
                "last_seen": 19.0,
                "interactions": 64,
            },
        },
        histories={7: [{"role": "user", "content": "hola"}]},
    )
    return state, counters


def test_reset_by_non_owner_is_rejected():
    state, _ = _dirty_state()
    ctx = _ctx(state, owner_id=1)
    message = FakeMessage(FakeAuthor(999), FakeChannel())

    run(season.handle(ctx, message))

    assert message.replies == ["Solo el dueño del canal puede reiniciar la temporada."]
    assert message.channel.sent == []
    # No se tocó nada.
    assert state.affinity["1"]["points"] == 72
    assert state.users["1"]["interactions"] == 72


def test_reset_zeroes_interactions_for_every_user():
    state, _ = _dirty_state()
    ctx = _ctx(state)
    message = FakeMessage(FakeAuthor(1), FakeChannel())

    run(season.handle(ctx, message))

    assert state.users["1"]["interactions"] == 0
    assert state.users["2"]["interactions"] == 0
    # Se conserva la identidad de los usuarios conocidos.
    assert state.users["1"]["name"] == "David"
    assert state.users["1"]["first_seen"] == 10.0


def test_reset_clears_affinity_memories_diary_dates_and_histories():
    state, _ = _dirty_state()
    ctx = _ctx(state)
    message = FakeMessage(FakeAuthor(1), FakeChannel())

    run(season.handle(ctx, message))

    assert state.affinity["1"]["points"] == 0
    assert state.affinity["1"]["milestones"] == []
    assert state.memories == {}
    assert state.dates == {}
    assert state.diary == []
    assert state.histories == {}
    assert state.world["winner_id"] is None
    assert state.world["relationship_started_at"] is None


def test_reset_advances_season_and_persists_all_stores():
    state, counters = _dirty_state()
    season_before = int(state.world.get("season", 1) or 1)
    ctx = _ctx(state)
    message = FakeMessage(FakeAuthor(1), FakeChannel())

    run(season.handle(ctx, message))

    assert int(state.world["season"]) == season_before + 1
    assert message.channel.sent and "Nueva temporada" in message.channel.sent[0]
    assert counters["world"] >= 1
    assert counters["affinity"] >= 1
    assert counters["users"] >= 1
    assert counters["dates"] >= 1
    assert counters["memories"] >= 1
    assert counters["diary"] >= 1


def test_reset_tolerates_non_dict_user_entries():
    state, _ = make_state(users={"1": "corrupto", "2": {"name": "X", "interactions": 5}})
    ctx = _ctx(state)
    message = FakeMessage(FakeAuthor(1), FakeChannel())

    run(season.handle(ctx, message))

    assert state.users["2"]["interactions"] == 0
