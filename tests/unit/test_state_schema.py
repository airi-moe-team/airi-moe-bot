"""Contrato del estado canónico (tarea 1.1)."""

from __future__ import annotations

import copy

import pytest

from airi.domain.state_schema import (
    CURRENT_SCHEMA_VERSION,
    validate_legacy_dataset,
    validate_state,
)


def valid_state():
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "state_version": 3,
        "world": {"season": 1},
        "affinity": {},
        "dates": {},
        "memories": {},
        "diary": [],
        "users": {},
        "histories": {},
        "turn_records": {},
        "message_index": {},
    }


def test_valid_state_is_accepted():
    result = validate_state(valid_state())
    assert result.ok is True
    assert result.errors == ()


def test_missing_required_key_is_rejected():
    data = valid_state()
    del data["memories"]
    result = validate_state(data)
    assert result.ok is False
    assert any("memories" in error for error in result.errors)


@pytest.mark.parametrize(
    ("key", "bad_value"),
    [
        ("world", []),
        ("affinity", []),
        ("dates", "no"),
        ("memories", None),
        ("diary", {}),
        ("users", []),
        ("histories", []),
        ("turn_records", []),
        ("message_index", []),
        ("state_version", "1"),
    ],
)
def test_wrong_type_is_rejected(key, bad_value):
    data = valid_state()
    data[key] = bad_value
    result = validate_state(data)
    assert result.ok is False
    assert any(key in error for error in result.errors)


def test_boolean_is_not_accepted_as_integer():
    data = valid_state()
    data["state_version"] = True
    result = validate_state(data)
    assert result.ok is False
    assert any("state_version" in error for error in result.errors)


def test_newer_schema_is_rejected():
    data = valid_state()
    data["schema_version"] = CURRENT_SCHEMA_VERSION + 1
    result = validate_state(data)
    assert result.ok is False
    assert any("schema_version" in error for error in result.errors)


def test_missing_schema_version_is_rejected():
    data = valid_state()
    del data["schema_version"]
    result = validate_state(data)
    assert result.ok is False


def test_archive_is_optional_but_must_be_an_object():
    data = valid_state()
    data["archive"] = []
    result = validate_state(data)
    assert result.ok is False

    data = valid_state()
    data["archive"] = {"last_season": 1}
    assert validate_state(data).ok is True


def test_validation_does_not_mutate_input():
    data = valid_state()
    before = copy.deepcopy(data)
    validate_state(data)
    assert data == before


@pytest.mark.parametrize(
    ("name", "value", "ok"),
    [
        ("world", {}, True),
        ("world", [], False),
        ("affinity", {"1": {}}, True),
        ("dates", {}, True),
        ("diary", [], True),
        ("diary", {}, False),
        ("memories", {}, True),
        ("users", {}, True),
        ("histories", {}, True),
    ],
)
def test_legacy_dataset_shapes(name, value, ok):
    assert validate_legacy_dataset(name, value).ok is ok


def test_unknown_legacy_dataset_is_rejected():
    assert validate_legacy_dataset("desconocido", {}).ok is False
