"""Idempotencia y reanudación tras reiniciar el proceso (tarea 6.4)."""

from __future__ import annotations

import asyncio

import pytest

from airi.adapters.state_store import StateStore
from airi.domain.turns import TurnStatus
from airi.services.bootstrap import bootstrap_state
from airi.services.conversation import ConversationService, TurnContext
from airi.services.migration import LegacyMigrator
from airi.services.persistence import StatePersistence
from airi.services.publication import PublicationResumer
from airi.services.turn_coordinator import TurnCoordinator
from airi.services.turn_journal import TurnJournal
from airi.testing import FakeLLM, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")


def run(coro):
    return asyncio.run(coro)


def make_coordinator(state, store, clock=lambda: NOW):
    persistence = StatePersistence(store)
    persistence.bind(state)
    journal = TurnJournal(state, persistence=persistence)
    service = ConversationService(
        llm=FakeLLM(replies=[llm_json("Hola", affinity_delta=2, affinity_event="alegría")]),
        state=state,
        clock=clock,
        date_delta_max=5,
    )
    return TurnCoordinator(
        service=service,
        journal=journal,
        persistence=persistence,
        commit_lock=asyncio.Lock(),
        clock=clock,
    ), journal, persistence


def reload_state(data_dir):
    store = StateStore(data_dir)
    result = bootstrap_state(store=store, migrator=LegacyMigrator(data_dir, store))
    journal = TurnJournal(result.state, persistence=result.persistence)
    return result, journal, store


def test_committed_message_is_not_reprocessed_after_restart(tmp_path):
    data_dir = tmp_path / "data"
    state, _ = make_state(world={"season": 1})
    store = StateStore(data_dir)
    coordinator, _, persistence = make_coordinator(state, store)
    persistence.save()

    async def publisher(committed):
        return None

    run(
        coordinator.execute(
            channel_id=7,
            user=DAVID,
            messages=[(DAVID, "hola")],
            message_ids=["100"],
            context=TurnContext(channel_id=7),
            publisher=publisher,
        )
    )

    boot, journal, _ = reload_state(data_dir)
    llm = FakeLLM(replies=[llm_json("NO DEBE EJECUTARSE")])
    service = ConversationService(
        llm=llm, state=boot.state, clock=lambda: NOW, date_delta_max=5
    )
    restarted = TurnCoordinator(
        service=service,
        journal=journal,
        persistence=boot.persistence,
        commit_lock=asyncio.Lock(),
        clock=lambda: NOW + 10,
    )
    result = run(
        restarted.execute(
            channel_id=7,
            user=DAVID,
            messages=[(DAVID, "hola")],
            message_ids=["100"],
            context=TurnContext(channel_id=7),
            publisher=lambda committed: asyncio.sleep(0),
        )
    )
    assert result is None
    assert llm.calls == []


def test_pending_publication_is_recovered_once_after_restart(tmp_path):
    data_dir = tmp_path / "data"
    state, _ = make_state(world={"season": 1})
    store = StateStore(data_dir)
    coordinator, journal, persistence = make_coordinator(state, store)
    persistence.save()

    async def broken(committed):
        raise RuntimeError("Discord caído")

    with pytest.raises(RuntimeError):
        run(
            coordinator.execute(
                channel_id=7,
                user=DAVID,
                messages=[(DAVID, "hola")],
                message_ids=["100"],
                context=TurnContext(channel_id=7),
                publisher=broken,
            )
        )
    assert journal.get("7:100").status is TurnStatus.COMMITTED

    boot, recovered_journal, _ = reload_state(data_dir)
    published = []

    async def publisher(record):
        published.append(record.reply_text)

    resumer = PublicationResumer(recovered_journal, ttl=900, clock=lambda: NOW + 10)
    assert run(resumer.resume(publisher)) == 1
    assert published == ["Hola"]
    assert recovered_journal.get("7:100").status is TurnStatus.PUBLISHED
    assert run(resumer.resume(publisher)) == 0
    assert len(published) == 1


def test_interrupted_processing_is_abandoned_after_restart(tmp_path):
    data_dir = tmp_path / "data"
    state, _ = make_state(world={"season": 1})
    store = StateStore(data_dir)
    _, journal, persistence = make_coordinator(state, store)
    persistence.save()
    journal.claim(7, ["100"], now=NOW)

    boot, recovered_journal, _ = reload_state(data_dir)
    count = recovered_journal.abandon_stale_processing(now=NOW + 1000, ttl=900)
    assert count == 1
    assert recovered_journal.get("7:100").status is TurnStatus.FAILED
