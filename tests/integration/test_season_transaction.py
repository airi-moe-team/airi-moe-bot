"""Reinicio de temporada transaccional y archivado (tareas 4.1-4.3)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from airi.adapters.state_store import AtomicWriteError, StateStore
from airi.discord_bot.commands import season
from airi.services.persistence import StatePersistence
from airi.services.season_archive import SeasonArchiveError, SeasonArchiver
from airi.testing import make_state


class FakeAuthor:
    def __init__(self, user_id):
        self.id = user_id


class FakeChannel:
    def __init__(self):
        self.id = 7
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)


class FakeMessage:
    def __init__(self, author, channel):
        self.author = author
        self.channel = channel
        self.replies = []

    async def reply(self, content=None, **kwargs):
        self.replies.append(content)


def run(coro):
    return asyncio.run(coro)


def make_ctx(tmp_path):
    data_dir = tmp_path / "data"
    store = StateStore(data_dir)
    state, _ = make_state(
        world={"season": 3, "winner_id": "1", "relationship_started_at": 10.0},
        affinity={"1": {"points": 90, "milestones": ["beso"]}},
        dates={"1": {"state": "active", "scene": "cena"}},
        memories={"1": [{"text": "ramen"}]},
        diary=[{"text": "un día"}],
        users={"1": {"name": "Ana", "interactions": 9}},
        histories={7: [{"role": "user", "content": "hola"}]},
    )
    state.turn_records = {
        "7:1": {
            "turn_key": "7:1",
            "channel_id": "7",
            "message_ids": ["1"],
            "status": "published",
            "reply_text": "",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
    }
    persistence = StatePersistence(store)
    persistence.bind(state)
    persistence.save()
    archiver = SeasonArchiver(data_dir)
    ctx = SimpleNamespace(
        owner_id=1,
        state=state,
        persistence=persistence,
        season_archiver=archiver,
        retention=None,
        lock=None,
    )
    return ctx, store, data_dir, persistence


def test_season_reset_archives_and_commits_once(tmp_path):
    ctx, store, data_dir, _ = make_ctx(tmp_path)
    message = FakeMessage(FakeAuthor(1), FakeChannel())

    run(season.handle(ctx, message))

    assert ctx.state.world["season"] == 4
    assert ctx.state.turn_records["7:1"]["status"] == "published"
    archive = data_dir / "archive" / "seasons" / "3" / "state.json"
    archived = json.loads(archive.read_text(encoding="utf-8"))
    assert archived["world"]["season"] == 3
    # El archivo conserva los usuarios de la temporada cerrada.
    assert archived["users"]["1"]["name"] == "Ana"
    active = json.loads(store.active_path.read_text(encoding="utf-8"))
    assert active["world"]["season"] == 4
    assert active["users"] == {}
    assert active["state_version"] == 2
    assert message.channel.sent and "Nueva temporada" in message.channel.sent[0]


def test_season_reset_write_failure_restores_state_and_silences_success(
    tmp_path, monkeypatch
):
    ctx, store, _, _ = make_ctx(tmp_path)
    message = FakeMessage(FakeAuthor(1), FakeChannel())
    original = store.save

    def failing_save(aggregate):
        raise AtomicWriteError("fallo simulado")

    monkeypatch.setattr(store, "save", failing_save)
    run(season.handle(ctx, message))

    assert ctx.state.world["season"] == 3
    assert ctx.state.affinity["1"]["points"] == 90
    assert ctx.state.users["1"]["name"] == "Ana"
    assert message.channel.sent == []
    assert message.replies and "No pude" in message.replies[0]
    # El archivo activo sigue en la versión anterior.
    active = json.loads(store.active_path.read_text(encoding="utf-8"))
    assert active["world"]["season"] == 3
    assert original is not None


def test_archive_failure_aborts_before_mutation(tmp_path, monkeypatch):
    ctx, _, _, _ = make_ctx(tmp_path)
    message = FakeMessage(FakeAuthor(1), FakeChannel())

    def failing_archive(**_kwargs):
        raise SeasonArchiveError("sin espacio")

    monkeypatch.setattr(ctx.season_archiver, "archive", failing_archive)
    run(season.handle(ctx, message))

    assert ctx.state.world["season"] == 3
    assert ctx.state.affinity["1"]["points"] == 90
    assert message.channel.sent == []
    assert message.replies and "No pude" in message.replies[0]


def test_season_reset_cancels_pending_proposals_and_resets_stages(tmp_path):
    ctx, _, _, persistence = make_ctx(tmp_path)
    ctx.state.world["relationships"] = {
        "1": {
            "stage": "enamored",
            "history": [
                {
                    "id": "r1",
                    "from": "interest",
                    "to": "enamored",
                    "evidence_kind": "support",
                    "reason": "Me apoyó",
                    "evidence_refs": ["turn:7:1"],
                    "evidence_summary": "Me apoyó.",
                    "season": 3,
                    "created_at": 10.0,
                }
            ],
            "pending_proposal": None,
        },
        "2": {
            "stage": "interest",
            "history": [],
            "pending_proposal": {"target_user_id": "2"},
        },
    }
    persistence.save()
    message = FakeMessage(FakeAuthor(1), FakeChannel())

    run(season.handle(ctx, message))

    record = ctx.state.world["relationships"]["1"]
    assert record["stage"] == "none"
    assert record["pending_proposal"] is None
    assert record["history"][0]["id"] == "r1"
    assert ctx.state.world["relationships"]["2"]["pending_proposal"] is None
    assert ctx.state.world["winner_id"] is None
