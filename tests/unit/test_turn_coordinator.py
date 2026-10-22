"""Orquestación de reclamación, commit y publicación (tarea 5.4)."""

from __future__ import annotations

import asyncio

import pytest

from airi.adapters.state_store import AtomicWriteError, StateStore
from airi.domain.turns import TurnStatus
from airi.services.conversation import ConversationService, TurnContext
from airi.services.persistence import StatePersistence
from airi.services.turn_coordinator import StaleTurnError, TurnCoordinator
from airi.services.turn_journal import TurnJournal
from airi.testing import FakeLLM, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")


def make_harness(tmp_path, service_cls=ConversationService):
    store = StateStore(tmp_path / "data")
    state, _ = make_state(world={"season": 1})
    persistence = StatePersistence(store)
    persistence.bind(state)
    persistence.save()
    journal = TurnJournal(state, persistence=persistence)
    llm = FakeLLM(replies=[llm_json("Hola", affinity_delta=2, affinity_event="alegría")])
    service = service_cls(
        llm=llm,
        state=state,
        clock=lambda: NOW,
        date_delta_max=5,
    )
    coordinator = TurnCoordinator(
        service=service,
        journal=journal,
        persistence=persistence,
        commit_lock=asyncio.Lock(),
        clock=lambda: NOW,
    )
    return state, store, journal, service, coordinator, llm


def run(coro):
    return asyncio.run(coro)


def test_execute_commits_then_publishes_and_marks(tmp_path):
    state, store, journal, _, coordinator, _ = make_harness(tmp_path)
    published = []

    async def publisher(committed):
        published.append(committed)

    result = run(
        coordinator.execute(
            channel_id=7,
            user=DAVID,
            messages=[(DAVID, "hola")],
            message_ids=["100"],
            context=TurnContext(channel_id=7),
            publisher=publisher,
        )
    )

    assert result is not None
    assert result.reply == "Hola"
    assert published and published[0].result.reply == "Hola"
    record = journal.get("7:100")
    assert record is not None
    assert record.status is TurnStatus.PUBLISHED
    active = __import__("json").loads(store.active_path.read_text(encoding="utf-8"))
    assert active["turn_records"]["7:100"]["status"] == "published"
    assert active["affinity"]["42"]["points"] == 2


def test_duplicate_does_not_call_model_or_publish(tmp_path):
    state, _, _, service, coordinator, llm = make_harness(tmp_path)
    published = []

    async def publisher(committed):
        published.append(committed)

    first = run(
        coordinator.execute(
            channel_id=7,
            user=DAVID,
            messages=[(DAVID, "hola")],
            message_ids=["100"],
            context=TurnContext(channel_id=7),
            publisher=publisher,
        )
    )
    calls_after_first = len(llm.calls)
    second = run(
        coordinator.execute(
            channel_id=7,
            user=DAVID,
            messages=[(DAVID, "hola")],
            message_ids=["100"],
            context=TurnContext(channel_id=7),
            publisher=publisher,
        )
    )
    assert first is not None
    assert second is None
    assert len(llm.calls) == calls_after_first
    assert len(published) == 1


def test_stale_season_does_not_apply_draft(tmp_path):
    class MutatingService(ConversationService):
        async def generate_turn(self, user, messages, ctx):
            draft = await super().generate_turn(user, messages, ctx)
            self.state.world["season"] = 2
            return draft

    state, _, journal, _, coordinator, _ = make_harness(
        tmp_path, service_cls=MutatingService
    )
    with pytest.raises(StaleTurnError):
        run(
            coordinator.execute(
                channel_id=7,
                user=DAVID,
                messages=[(DAVID, "hola")],
                message_ids=["100"],
                context=TurnContext(channel_id=7),
                publisher=lambda committed: asyncio.sleep(0),
            )
        )
    assert state.affinity.get("42") in (None, {})
    assert state.histories == {}
    assert journal.get("7:100").status is TurnStatus.FAILED


def test_commit_failure_does_not_publish(tmp_path, monkeypatch):
    state, store, journal, _, coordinator, _ = make_harness(tmp_path)
    published = []

    async def publisher(committed):
        published.append(committed)

    def failing_save(aggregate):
        raise AtomicWriteError("sin espacio")

    monkeypatch.setattr(store, "save", failing_save)
    with pytest.raises(Exception):
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
    assert published == []
    assert state.world["season"] == 1


def test_publisher_failure_leaves_committed_for_resume(tmp_path):
    _, _, journal, _, coordinator, _ = make_harness(tmp_path)

    async def broken_publisher(committed):
        raise RuntimeError("Discord caído")

    with pytest.raises(RuntimeError):
        run(
            coordinator.execute(
                channel_id=7,
                user=DAVID,
                messages=[(DAVID, "hola")],
                message_ids=["100"],
                context=TurnContext(channel_id=7),
                publisher=broken_publisher,
            )
        )
    record = journal.get("7:100")
    assert record is not None
    assert record.status is TurnStatus.COMMITTED
    assert journal.pending_publications(now=NOW, ttl=900)


def test_turn_key_is_exposed_as_an_available_evidence_reference(tmp_path):
    _, _, _, _, coordinator, llm = make_harness(tmp_path)

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
    assert "turn:7:100" in llm.last_system_prompt


def test_a_relationship_change_during_generation_discards_the_draft(tmp_path):
    from airi.domain.turn_guard import GuardDecision

    state, _, _, service, coordinator, _ = make_harness(tmp_path)
    original = service.generate_turn

    async def generate_then_change_relationship(user, messages, ctx):
        draft = await original(user, messages, ctx)
        state.world["relationships"] = {
            "42": {
                "stage": "interest",
                "history": [
                    {
                        "id": "r1",
                        "from": "curiosity",
                        "to": "interest",
                        "evidence_kind": "support",
                        "reason": "Me apoyó",
                        "evidence_refs": ["turn:9:9"],
                        "evidence_summary": "Me apoyó.",
                        "season": 1,
                        "created_at": NOW,
                    }
                ],
                "pending_proposal": None,
            }
        }
        return draft

    service.generate_turn = generate_then_change_relationship

    async def publisher(committed):
        return None

    with pytest.raises(StaleTurnError) as exc:
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
    assert exc.value.decision is GuardDecision.STALE_RELATIONSHIP
