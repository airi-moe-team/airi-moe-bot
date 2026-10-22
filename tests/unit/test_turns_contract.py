"""Contratos de turno: clave, estado y serialización (tarea 1.2)."""

from __future__ import annotations

import pytest

from airi.domain.turns import (
    TransitionError,
    TurnRecord,
    TurnStatus,
    can_transition,
    hash_text,
    make_turn_key,
    new_turn_record,
    transition,
)


def test_turn_key_is_stable_and_uses_first_message():
    first = make_turn_key(123, ["900", "901"])
    assert first == make_turn_key(123, ("900", "901"))
    assert first == "123:900"
    assert make_turn_key(123, ["901"]) != first


def test_turn_key_requires_at_least_one_message():
    with pytest.raises(ValueError):
        make_turn_key(123, [])


def test_hash_text_is_stable_and_sensitive():
    assert hash_text("hola") == hash_text("hola")
    assert hash_text("hola") != hash_text("adiós")


@pytest.mark.parametrize(
    ("current", "new", "allowed"),
    [
        (TurnStatus.PROCESSING, TurnStatus.COMMITTED, True),
        (TurnStatus.PROCESSING, TurnStatus.FAILED, True),
        (TurnStatus.COMMITTED, TurnStatus.PUBLISHED, True),
        (TurnStatus.COMMITTED, TurnStatus.FAILED, True),
        (TurnStatus.PUBLISHED, TurnStatus.FAILED, False),
        (TurnStatus.FAILED, TurnStatus.COMMITTED, False),
        (TurnStatus.PUBLISHED, TurnStatus.COMMITTED, False),
    ],
)
def test_status_transitions(current, new, allowed):
    assert can_transition(current, new) is allowed
    if allowed:
        assert transition(current, new) is new
    else:
        with pytest.raises(TransitionError):
            transition(current, new)


def test_same_status_is_not_a_transition():
    assert can_transition(TurnStatus.PROCESSING, TurnStatus.PROCESSING) is False


def test_record_round_trip():
    record = new_turn_record(
        turn_key="1:2",
        channel_id=1,
        message_ids=["2", "3"],
        status=TurnStatus.PROCESSING,
        reply_text="",
        now=10.0,
    )
    payload = record.to_dict()
    assert payload["status"] == "processing"
    assert payload["message_ids"] == ["2", "3"]
    assert TurnRecord.from_dict(payload) == record


def test_record_updates_are_immutable_copies():
    record = new_turn_record(
        turn_key="1:2",
        channel_id=1,
        message_ids=["2"],
        status=TurnStatus.COMMITTED,
        reply_text="Hola",
        now=10.0,
    )
    updated = record.with_status(TurnStatus.PUBLISHED, now=12.0, published_at=12.0)
    assert record.status is TurnStatus.COMMITTED
    assert record.published_at is None
    assert updated.status is TurnStatus.PUBLISHED
    assert updated.published_at == 12.0
    assert updated.updated_at == 12.0
    assert updated.reply_text == "Hola"


def test_record_from_dict_rejects_invalid_status():
    with pytest.raises(ValueError):
        TurnRecord.from_dict(
            {
                "turn_key": "1:2",
                "channel_id": "1",
                "message_ids": ["2"],
                "status": "inventado",
                "reply_text": "",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
