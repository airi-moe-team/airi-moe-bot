import pytest

from airi.coordinator.policy import ParticipationPolicy
from airi.coordinator.store import ChannelCoordinator, Conflict


@pytest.fixture
def scheduler(tmp_path):
    now = [1000.0]
    store = ChannelCoordinator(
        tmp_path / "coord.sqlite3",
        {"airi": "10", "luna": "20"},
        channel_id="7",
        clock=lambda: now[0],
        policy=ParticipationPolicy(max_interventions=2, turn_delay_seconds=3),
    )
    for bot, uid in store.bots.items():
        store.register(bot, discord_id=uid)
    yield store, now
    store.close()


def event(identifier="100", **changes):
    return {
        "id": identifier,
        "channel_id": "7",
        "author_id": "42",
        "name": "David",
        "kind": "human",
        "content": "hola",
        "mentions": [],
        **changes,
    }


def claim(store, now, bot="airi"):
    now[0] += 3
    job = store.claim(bot)
    if job and job["kind"] == "decision":
        store.complete(
            job["id"],
            bot,
            outcome="decision",
            decision={
                "participate": True,
                "reason_code": "relevant",
            },
        )
        return store.claim(bot)
    return job


def test_duplicate_events_and_bounded_round(scheduler):
    store, now = scheduler
    assert not store.ingest(event())["duplicate"]
    assert store.ingest(event())["duplicate"]
    first = claim(store, now)
    store.ready(first["id"], "airi")
    store.ingest(event("101", author_id="10", name="Airi", kind="bot", content="Hola David"))
    store.complete(first["id"], "airi", outcome="published", sent=["101"])
    assert store.claim("luna") is None  # give humans time to intervene
    second = claim(store, now, "luna")
    assert second["kind"] == "peer"
    assert second["history"][-1]["author_id"] == "10"
    store.ready(second["id"], "luna")
    store.ingest(event("102", author_id="20", name="Luna", kind="bot"))
    store.complete(second["id"], "luna", outcome="published", sent=["102"])
    assert store.claim("airi") is None
    assert store.claim("luna") is None


@pytest.mark.parametrize(
    ("changes", "bot", "kind"),
    [
        ({"mentions": ["20"]}, "luna", "human"),
        ({"reply_author_id": "20"}, "luna", "human"),
        ({"mentions": ["10"], "reply_author_id": "20"}, "airi", "human"),
        ({"content": "!ayuda"}, "airi", "command"),
        ({"content": "<@20> !regalo <@10>", "mentions": ["20", "10"]}, "luna", "command"),
    ],
)
def test_routing(scheduler, changes, bot, kind):
    store, now = scheduler
    store.ingest(event(**changes))
    job = claim(store, now, bot)
    assert job["kind"] == kind
    assert not job["allow_reply"]
    if "regalo" in changes.get("content", ""):
        assert job["event"]["content"] == "!regalo <@10>"


def test_two_mentions_allow_companion(scheduler):
    store, now = scheduler
    store.ingest(event(mentions=["10", "20"]))
    assert claim(store, now)["allow_reply"]


def test_bot_mention_in_command_arguments_does_not_select_recipient(scheduler):
    store, now = scheduler
    store.ingest(event(content="!regalo <@20>", mentions=["20"]))
    job = claim(store, now, "airi")
    assert job["kind"] == "command"
    assert job["event"]["content"] == "!regalo <@20>"


def test_merge_same_author_without_switching_bot(scheduler):
    store, now = scheduler
    store.ingest(event(content="hola"))
    now[0] += 1
    store.ingest(event("101", content="¿qué tal?"))
    job = claim(store, now)
    assert job["parts"] == ["hola", "¿qué tal?"]
    assert job["source_ids"] == ["100", "101"]


def test_different_authors_are_not_merged(scheduler):
    store, now = scheduler
    store.ingest(event())
    store.ingest(event("101", author_id="43", content="otra persona"))
    job = claim(store, now, "luna")
    assert job["source_ids"] == ["101"]
    assert len(job["history"]) == 2


def test_human_interrupts_generation_without_concurrent_llm(scheduler):
    store, now = scheduler
    store.ingest(event())
    first = claim(store, now)
    store.ingest(event("101", author_id="43"))
    assert claim(store, now, "luna") is None
    with pytest.raises(Conflict):
        store.ready(first["id"], "airi")
    store.complete(first["id"], "airi", outcome="failed")
    assert store.claim("luna")["author_id"] == "43"


def test_human_interrupts_queued_peer(scheduler):
    store, now = scheduler
    store.ingest(event())
    first = claim(store, now)
    store.ready(first["id"], "airi")
    store.complete(first["id"], "airi", outcome="published")
    store.ingest(event("101", mentions=["10"]))
    assert claim(store, now, "luna") is None
    assert store.claim("airi")["kind"] == "human"


def test_date_owner_blocks_peer_but_allows_targeted_commands(scheduler):
    store, now = scheduler
    store.register("luna", discord_id="20", date_active=True)
    store.ingest(event())
    job = claim(store, now, "luna")
    assert not job["allow_reply"]
    store.ready(job["id"], "luna")
    store.complete(job["id"], "luna", outcome="published")
    store.ingest(event("101", content="!ayuda"))
    assert store.claim("airi")["kind"] == "command"


def test_expiry_releases_generation_but_not_uncertain_publication(scheduler):
    store, now = scheduler
    store.ingest(event())
    job = claim(store, now)
    store.ready(job["id"], "airi")
    now[0] += 361
    assert store.claim("luna") is None
    assert store.uncertain("airi")[0]["id"] == job["id"]
    with pytest.raises(Conflict):
        store.sending(job["id"], "airi", {"content": "late"})


def test_restart_preserves_history_and_alternation_without_resend(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = ChannelCoordinator(path, {"airi": "10", "luna": "20"}, channel_id="7", debounce=0)
    for bot, uid in store.bots.items():
        store.register(bot, discord_id=uid)
    store.ingest(event())
    job = store.claim("airi")
    store.complete(
        job["id"],
        "airi",
        outcome="decision",
        decision={
            "participate": True,
            "reason_code": "relevant",
        },
    )
    job = store.claim("airi")
    store.ready(job["id"], "airi")
    store.sending(job["id"], "airi", {"content": "possibly sent"})
    store.close()
    store = ChannelCoordinator(path, {"airi": "10", "luna": "20"}, channel_id="7", debounce=0)
    assert store.uncertain("airi")[0]["intents"][0]["content"] == "possibly sent"
    assert store.history()[0]["content"] == "hola"
    assert store._state()["next"] == "luna"
    assert store.claim("airi") is None
    store.complete(job["id"], "airi", outcome="reconciled", sent=["200"])
    store.close()


def test_out_of_order_reconnect_does_not_replace_new_turn(scheduler):
    store, now = scheduler
    store.ingest(event("200"))
    assert store.ingest(event("100"))["historical"]
    job = claim(store, now)
    assert job["source_ids"] == ["200"]
    assert [e["id"] for e in job["history"]] == ["100", "200"]


def test_unavailable_worker_and_invalid_participants(scheduler):
    store, now = scheduler
    with pytest.raises(ValueError):
        store.ingest(event(author_id="99", kind="bot"))
    with pytest.raises(ValueError):
        store.ingest(event(channel_id="8"))
    with pytest.raises(Conflict):
        store.register("luna", discord_id="10")
    store.register("luna", discord_id="20", available=False)
    store.ingest(event())
    assert claim(store, now) is None


def test_history_limits(scheduler):
    store, _ = scheduler
    for index in range(100, 140):
        store.ingest(event(str(index), content="x" * 1000))
    history = store.history()
    assert len(history) <= 30
    assert sum(len(e["content"]) for e in history) <= 16000
    assert history[-1]["id"] == "139"


def test_database_cannot_be_reused_for_another_channel(tmp_path):
    path = tmp_path / "coordinator.sqlite3"
    store = ChannelCoordinator(path, {"airi": "10", "luna": "20"}, channel_id="7")
    store.close()
    with pytest.raises(ValueError, match="different Discord"):
        ChannelCoordinator(path, {"airi": "10", "luna": "20"}, channel_id="8")
