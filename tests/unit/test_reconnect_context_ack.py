"""El contexto de reconexión se persiste como entregado sin repetirse."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

from airi.discord_bot.client import acknowledge_reconnect_context
from airi.services.state import AppState


class FakePersistence:
    def __init__(self):
        self.transactions = 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield


def _state(**entry):
    return AppState(world={"last_shutdown": entry})


def test_marks_context_delivered_and_saves():
    state = _state(kind="self", reason="me fui a dormir", status="confirmed")
    saved = []
    state.save_world = lambda: saved.append(True)
    persistence = FakePersistence()
    ctx = SimpleNamespace(state=state, persistence=persistence)

    asyncio.run(acknowledge_reconnect_context(ctx))

    assert state.world["last_shutdown"]["context_delivered"] is True
    assert saved == [True]
    assert persistence.transactions == 1


def test_already_delivered_is_a_noop():
    state = _state(
        kind="self",
        reason="me fui a dormir",
        status="confirmed",
        context_delivered=True,
    )
    saved = []
    state.save_world = lambda: saved.append(True)
    persistence = FakePersistence()
    ctx = SimpleNamespace(state=state, persistence=persistence)

    asyncio.run(acknowledge_reconnect_context(ctx))

    assert saved == []
    assert persistence.transactions == 0


def test_without_persistence_marks_only_in_memory():
    state = _state(kind="self", reason="me fui a dormir", status="confirmed")
    ctx = SimpleNamespace(state=state, persistence=None)

    asyncio.run(acknowledge_reconnect_context(ctx))

    assert state.world["last_shutdown"]["context_delivered"] is True
