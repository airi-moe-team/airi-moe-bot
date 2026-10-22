"""Registro durable de turnos (tarea 5.1)."""

from __future__ import annotations

from airi.domain.turns import TurnStatus
from airi.services.state import AppState
from airi.services.turn_journal import ClaimStatus, TurnJournal


def make_state():
    return AppState(world={"season": 1})


def test_claim_new_turn_indexes_all_messages():
    state = make_state()
    journal = TurnJournal(state)
    claim = journal.claim(7, ["100", "101"], now=10.0)
    assert claim.status is ClaimStatus.CLAIMED
    assert claim.turn_key == "7:100"
    assert set(state.message_index) == {"7:100", "7:101"}
    assert state.turn_records["7:100"]["status"] == "processing"


def test_duplicate_message_is_rejected():
    state = make_state()
    journal = TurnJournal(state)
    journal.claim(7, ["100"], now=10.0)
    duplicate = journal.claim(7, ["100"], now=11.0)
    assert duplicate.status is ClaimStatus.DUPLICATE
    assert duplicate.turn_key == "7:100"


def test_duplicate_inside_batch_is_rejected():
    state = make_state()
    journal = TurnJournal(state)
    journal.claim(7, ["100"], now=10.0)
    duplicate = journal.claim(7, ["100", "101"], now=11.0)
    assert duplicate.status is ClaimStatus.DUPLICATE
    assert "7:101" not in state.message_index


def test_status_transitions_and_reply_text():
    state = make_state()
    journal = TurnJournal(state)
    claim = journal.claim(7, ["100"], now=10.0)
    committed = journal.mark_committed(claim.turn_key, "Hola", now=11.0)
    assert committed is not None
    assert committed.status is TurnStatus.COMMITTED
    assert committed.reply_text == "Hola"
    published = journal.mark_published(claim.turn_key, now=12.0)
    assert published is not None
    assert published.status is TurnStatus.PUBLISHED


def test_failed_transition():
    state = make_state()
    journal = TurnJournal(state)
    claim = journal.claim(7, ["100"], now=10.0)
    failed = journal.mark_failed(claim.turn_key, "timeout", now=11.0)
    assert failed is not None
    assert failed.status is TurnStatus.FAILED
    assert "timeout" in failed.failure_reason


def test_pending_publications_respects_ttl():
    state = make_state()
    journal = TurnJournal(state)
    recent = journal.claim(7, ["100"], now=10.0)
    old = journal.claim(7, ["101"], now=10.0)
    journal.mark_committed(old.turn_key, "antigua", now=20.0)
    journal.mark_committed(recent.turn_key, "reciente", now=70.0)
    pending = journal.pending_publications(now=80.0, ttl=20.0)
    assert [record.turn_key for record in pending] == ["7:100"]
    assert journal.pending_publications(now=100.0, ttl=20.0) == ()


def test_abandon_stale_processing():
    state = make_state()
    journal = TurnJournal(state)
    stale = journal.claim(7, ["100"], now=10.0)
    fresh = journal.claim(8, ["200"], now=100.0)
    count = journal.abandon_stale_processing(now=110.0, ttl=50.0)
    assert count == 1
    assert state.turn_records[stale.turn_key]["status"] == "failed"
    assert state.turn_records[fresh.turn_key]["status"] == "processing"


def test_prune_removes_resolved_turns_and_index():
    state = make_state()
    journal = TurnJournal(state)
    claim = journal.claim(7, ["100"], now=10.0)
    journal.mark_committed(claim.turn_key, "hola", now=11.0)
    journal.mark_published(claim.turn_key, now=12.0)
    removed = journal.prune(now=1000.0, retain_seconds=100.0)
    assert removed == 1
    assert state.turn_records == {}
    assert state.message_index == {}


def test_prune_keeps_pending_and_recent():
    state = make_state()
    journal = TurnJournal(state)
    pending = journal.claim(7, ["100"], now=10.0)
    journal.mark_committed(pending.turn_key, "hola", now=11.0)
    removed = journal.prune(now=1000.0, retain_seconds=100.0)
    assert removed == 0
    assert pending.turn_key in state.turn_records
