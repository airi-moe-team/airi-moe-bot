import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from airi.coordinator.policy import ParticipationPolicy
from airi.coordinator.store import ChannelCoordinator, Conflict

START = datetime(2026, 11, 7, 15, tzinfo=timezone.utc).timestamp()  # 10am Lima
BOTS = {"airi": "10", "luna": "20"}


class Harness:
    def __init__(self, path, policy=None):
        self.path = path
        self.now = START
        self.policy = policy or ParticipationPolicy()
        self.store = self.open()
        self.refresh()

    def open(self):
        return ChannelCoordinator(
            self.path, BOTS, channel_id="7", clock=lambda: self.now, policy=self.policy, debounce=0
        )

    def refresh(self):
        for bot, uid in BOTS.items():
            old = self.store.workers.get(bot, {})
            self.store.register(
                bot,
                discord_id=uid,
                date_active=old.get("date", False),
                available=old.get("available", True),
            )

    def advance(self, seconds):
        self.now += seconds
        self.refresh()

    def event(self, identifier="100", **values):
        return {
            "id": identifier,
            "channel_id": "7",
            "author_id": "42",
            "name": "David",
            "kind": "human",
            "content": "necesitamos un desempate",
            "mentions": [],
            "timestamp": self.now,
            **values,
        }

    def decide(self, job, participate=True):
        self.store.complete(
            job["id"],
            job["bot"],
            outcome="decision",
            decision={
                "participate": participate,
                "reason_code": "relevant" if participate else "no_contribution",
            },
        )
        return self.store.claim(job["bot"]) if participate else None

    def publish(self, job, sent=("200",)):
        self.store.ready(job["id"], job["bot"])
        self.store.complete(job["id"], job["bot"], outcome="published", sent=sent)

    def idle(self):
        self.advance(self.policy.idle_seconds)
        return self.store.tick()

    def stop_peer(self, bot):
        self.advance(self.policy.turn_delay_seconds)
        job = self.store.claim(bot)
        self.decide(job, False)


@pytest.fixture
def harness(tmp_path):
    value = Harness(tmp_path / "state.sqlite3")
    yield value
    value.store.close()


def test_general_conversation_can_be_silent_without_consulting_sister(harness):
    h = harness
    h.store.ingest(h.event(content="yo salgo a las nueve"))
    job = h.store.claim("airi")
    assert job["kind"] == "decision"
    with pytest.raises(Conflict):
        h.store.ready(job["id"], "airi")
    h.decide(job, False)
    assert h.store.claim("luna") is None
    assert not h.store._busy()
    assert h.store._state()["daily_counts"] == {}


def test_six_interventions_total_and_chunks_count_once(harness):
    h = harness
    h.store.ingest(h.event())
    bot = "airi"
    for count in range(1, 7):
        job = h.store.claim(bot)
        assert job["kind"] == "decision"
        generation = h.decide(job)
        h.publish(generation, sent=["200", "201"])
        assert h.store._round(generation)["count"] == count
        # Retrying the same acknowledgement cannot spend budget twice.
        h.store.complete(generation["id"], bot, outcome="published", sent=["200", "201"])
        assert h.store._round(generation)["count"] == count
        bot = "luna" if bot == "airi" else "airi"
        h.advance(8)
    assert h.store.claim(bot) is None
    assert not h.store._busy()


def test_idle_threshold_silence_recheck_and_separate_alternation(harness):
    h = harness
    h.advance(1799)
    assert h.store.tick() is None
    h.advance(1)
    offered = h.store.tick()
    assert offered["bot"] == "airi"
    assert h.store.tick() is None
    h.decide(h.store.claim("airi"), False)
    assert h.store._state()["daily_counts"] == {}
    assert h.store._state()["next"] == "airi"
    h.advance(1799)
    assert h.store.tick() is None
    h.advance(1)
    assert h.store.tick()["bot"] == "luna"


def test_cooldown_starts_at_end_and_not_at_decision(harness):
    h = harness
    h.idle()
    generation = h.decide(h.store.claim("airi"))
    assert h.store._state()["daily_counts"] == {}
    h.publish(generation)
    day = h.policy.local_date(h.now)
    assert h.store._state()["daily_counts"][day] == 1
    h.stop_peer("luna")
    end = h.now
    assert h.store._state()["cooldown_until"] == end + 10800
    h.advance(10799)
    assert h.store.tick() is None
    h.advance(1)
    assert h.store.tick()["bot"] == "luna"


def test_shared_daily_limit_and_midnight_reset(tmp_path):
    policy = ParticipationPolicy(
        idle_seconds=1,
        cooldown_seconds=1,
        recheck_seconds=1,
        turn_delay_seconds=1,
        max_interventions=1,
        start_hour=0,
        end_hour=23,
    )
    h = Harness(tmp_path / "daily.sqlite3", policy)
    try:
        for expected in range(1, 4):
            h.advance(1)
            offered = h.store.tick()
            assert offered
            generation = h.decide(h.store.claim(offered["bot"]))
            h.publish(generation)
            assert h.store._state()["daily_counts"][policy.local_date(h.now)] == expected
        h.advance(1)
        assert h.store.tick() is None
        h.now = datetime(2026, 11, 8, 5, tzinfo=timezone.utc).timestamp()  # midnight Lima
        h.refresh()
        assert h.store.tick() is not None
    finally:
        h.store.close()


def test_human_without_text_cancels_idle_decision(harness):
    h = harness
    h.idle()
    decision = h.store.claim("airi")
    h.store.ingest(h.event(content=""))
    h.decide(decision)
    assert h.store.get_job(decision["id"], "airi")["status"] == "cancelled"
    assert not h.store._busy()
    assert h.store.tick() is None
    assert h.store._state()["daily_counts"] == {}


def test_human_cancels_generation_and_re_evaluates_new_message(harness):
    h = harness
    h.idle()
    generation = h.decide(h.store.claim("airi"))
    h.store.ingest(h.event())
    with pytest.raises(Conflict):
        h.store.ready(generation["id"], "airi")
    h.store.complete(generation["id"], "airi", outcome="failed")
    next_job = h.store.claim("airi")
    assert next_job["kind"] == "decision"
    assert next_job["target_kind"] == "human"


def test_human_interrupt_after_authorization_allows_finish_without_continuation(harness):
    h = harness
    h.idle()
    generation = h.decide(h.store.claim("airi"))
    h.store.ready(generation["id"], "airi")
    h.store.ingest(h.event())
    h.store.sending(generation["id"], "airi", {"content": "ya autorizada"})
    h.store.complete(generation["id"], "airi", outcome="published", sent=["200"])
    next_job = h.store.claim("airi")
    assert next_job["kind"] == "decision" and next_job["target_kind"] == "human"


def test_window_rechecked_before_decision_acceptance_and_first_publish(harness):
    h = harness
    h.now = datetime(2026, 11, 8, 3, 59, tzinfo=timezone.utc).timestamp()
    h.refresh()
    h.store.tick()
    decision = h.store.claim("airi")
    generation = h.decide(decision)
    h.advance(60)  # 23:00 Lima
    with pytest.raises(Conflict):
        h.store.ready(generation["id"], "airi")
    h.store.complete(generation["id"], "airi", outcome="failed")
    assert not h.store._busy()
    assert h.store._state()["daily_counts"] == {}


def test_existing_exchange_can_finish_after_window_closes(harness):
    h = harness
    h.now = datetime(2026, 11, 8, 3, 59, 59, tzinfo=timezone.utc).timestamp()
    h.refresh()
    h.store.tick()
    generation = h.decide(h.store.claim("airi"))
    h.publish(generation)
    h.advance(8)
    peer = h.decide(h.store.claim("luna"))
    h.publish(peer)
    assert h.store._round(peer)["count"] == 2


@pytest.mark.parametrize("blocker", ["disabled", "date", "unavailable", "uncertain"])
def test_idle_opportunities_respect_blockers(harness, blocker):
    h = harness
    h.advance(1800)
    if blocker == "disabled":
        h.store.policy = replace(h.policy, proactive_enabled=False)
    elif blocker == "date":
        h.store.register("luna", discord_id="20", date_active=True)
    elif blocker == "unavailable":
        h.store.register("luna", discord_id="20", available=False)
    else:
        h.store.ingest(h.event(mentions=["10"]))
        job = h.store.claim("airi")
        h.store.ready(job["id"], "airi")
        h.store.complete(job["id"], "airi", outcome="uncertain")
    assert h.store.tick() is None


def test_old_outbox_event_is_context_not_new_work(harness):
    h = harness
    h.advance(1800)
    h.store.ingest(h.event(timestamp=START - 3600))
    assert h.store._state()["activity_at"] == START
    assert not h.store._busy()
    assert h.store.history()[0]["content"] == "necesitamos un desempate"
    assert h.store.tick()


def test_restart_preserves_counters_and_does_not_replay_idle_work(harness):
    h = harness
    h.idle()
    generation = h.decide(h.store.claim("airi"))
    h.publish(generation)
    h.stop_peer("luna")
    before = h.store._state()
    h.store.close()
    h.store = h.open()
    h.refresh()
    after = h.store._state()
    assert after["daily_counts"] == before["daily_counts"]
    assert after["cooldown_until"] == before["cooldown_until"]
    assert after["proactive_next"] == "luna"
    assert h.store.tick() is None


def test_failed_decision_does_not_spend_quota_or_retry_immediately(harness):
    h = harness
    h.idle()
    job = h.store.claim("airi")
    h.store.complete(job["id"], "airi", outcome="failed")
    assert h.store._state()["daily_counts"] == {}
    assert h.store.tick() is None
    assert h.store.claim("luna") is None


def test_restart_uncertain_first_publication_blocks_and_is_accounted_once(harness):
    h = harness
    h.idle()
    generation = h.decide(h.store.claim("airi"))
    h.store.ready(generation["id"], "airi")
    h.store.sending(generation["id"], "airi", {"content": "maybe sent"})
    h.store.close()
    h.store = h.open()
    h.refresh()
    assert h.store.uncertain("airi")
    assert h.store.tick() is None
    h.store.complete(generation["id"], "airi", outcome="reconciled", sent=["200"])
    h.store.complete(generation["id"], "airi", outcome="reconciled", sent=["200"])
    assert h.store._state()["daily_counts"][h.policy.local_date(h.now)] == 1
    assert h.store.tick() is None


def test_expired_positive_decision_cannot_create_a_generation(harness):
    h = harness
    h.idle()
    decision = h.store.claim("airi")
    h.advance(361)
    assert h.decide(decision) is None
    assert h.store.get_job(decision["id"], "airi")["status"] == "cancelled"
    assert not h.store._busy()
    assert not h.store._state()["daily_counts"]


def test_upgrade_preserves_old_state_and_blocks_uncertain_publications(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE events(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE jobs(id TEXT PRIMARY KEY,status TEXT NOT NULL,bot TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE state(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
        """)
        db.execute(
            "INSERT INTO state VALUES (?,?)",
            ("channel", json.dumps({"revision": 4, "next": "luna"})),
        )
        event = {
            "id": "100",
            "author_id": "42",
            "name": "David",
            "kind": "human",
            "content": "public context",
        }
        db.execute("INSERT INTO events VALUES (?,?)", ("100", json.dumps(event)))
        for identifier, status in [("queued", "queued"), ("sending", "publishing")]:
            job = {
                "id": identifier,
                "round": identifier,
                "bot": "airi",
                "kind": "human",
                "revision": 4,
                "status": status,
            }
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?)", (identifier, status, "airi", json.dumps(job))
            )
    store = ChannelCoordinator(path, BOTS, channel_id="7", clock=lambda: START)
    try:
        assert store._state()["next"] == "luna"
        assert store.history()[0]["content"] == "public context"
        assert store.get_job("queued", "airi")["status"] == "cancelled"
        assert store.get_job("sending", "airi")["status"] == "uncertain"
        assert store.tick() is None
    finally:
        store.close()
