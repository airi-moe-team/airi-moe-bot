"""Almacén atómico y recuperación del estado (tarea 2.1 y 2.2)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from airi.adapters.state_store import (
    AtomicWriteError,
    StateStore,
    StateValidationError,
)
from airi.ports.state_store import LoadStatus


def aggregate(version=1, season=1, diary=None):
    return {
        "schema_version": 1,
        "state_version": version,
        "world": {"season": season},
        "affinity": {},
        "dates": {},
        "memories": {},
        "diary": list(diary or []),
        "users": {},
        "histories": {},
        "turn_records": {},
        "message_index": {},
    }


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path / "data")


def test_save_writes_valid_active_file(store):
    result = store.save(aggregate(version=1))
    assert result.ok is True
    assert result.state_version == 1
    payload = json.loads(store.active_path.read_text(encoding="utf-8"))
    assert payload["state_version"] == 1
    assert oct(store.active_path.stat().st_mode & 0o777) == "0o600"


def test_second_save_rotates_a_valid_backup(store):
    store.save(aggregate(version=1))
    store.save(aggregate(version=2, season=2))
    active = json.loads(store.active_path.read_text(encoding="utf-8"))
    backup = json.loads(store.backup_path.read_text(encoding="utf-8"))
    assert active["state_version"] == 2
    assert backup["state_version"] == 1
    assert oct(store.backup_path.stat().st_mode & 0o777) == "0o600"


def test_invalid_aggregate_does_not_touch_files(store):
    with pytest.raises(StateValidationError):
        store.save({"schema_version": 1})
    assert not store.active_path.exists()
    assert not store.backup_path.exists()


def test_failure_replacing_active_keeps_previous_state(store, monkeypatch):
    store.save(aggregate(version=1, season=1))
    previous = store.active_path.read_bytes()
    original_replace = os.replace

    def failing_replace(src, dst):
        if Path(dst) == store.active_path:
            raise OSError("fallo simulado al reemplazar el activo")
        return original_replace(src, dst)

    monkeypatch.setattr("airi.adapters.state_store.os.replace", failing_replace)
    with pytest.raises(AtomicWriteError):
        store.save(aggregate(version=2, season=2))
    assert store.active_path.read_bytes() == previous


def test_failure_rotating_backup_keeps_active_state(store, monkeypatch):
    store.save(aggregate(version=1, season=1))
    previous = store.active_path.read_bytes()
    original_replace = os.replace

    def failing_replace(src, dst):
        if Path(dst) == store.backup_path:
            raise OSError("fallo simulado al rotar la copia")
        return original_replace(src, dst)

    monkeypatch.setattr("airi.adapters.state_store.os.replace", failing_replace)
    with pytest.raises(AtomicWriteError):
        store.save(aggregate(version=2, season=2))
    assert store.active_path.read_bytes() == previous


def test_missing_state_returns_missing(store):
    result = store.load()
    assert result.status is LoadStatus.MISSING
    assert result.data is None
    assert result.recovered is False


def test_valid_state_loads(store):
    store.save(aggregate(version=3, season=4))
    result = store.load()
    assert result.status is LoadStatus.OK
    assert result.data["state_version"] == 3
    assert result.recovered is False


def test_corrupt_active_recovers_from_backup_and_quarantines(store):
    store.save(aggregate(version=1, season=1))
    store.save(aggregate(version=2, season=2))
    store.active_path.write_text("{no es json", encoding="utf-8")

    result = store.load()
    assert result.status is LoadStatus.OK
    assert result.recovered is True
    assert result.data["state_version"] == 1
    assert Path(result.quarantine_path).exists()
    assert Path(result.quarantine_path).read_text(encoding="utf-8") == "{no es json"
    assert json.loads(store.active_path.read_text(encoding="utf-8"))["state_version"] == 1


def test_missing_active_recovers_from_backup(store):
    store.save(aggregate(version=1))
    store.save(aggregate(version=2))
    store.active_path.unlink()
    result = store.load()
    assert result.status is LoadStatus.OK
    assert result.recovered is True
    assert result.data["state_version"] == 1


def test_corrupt_active_and_backup_blocks_without_overwrite(store):
    store.save(aggregate(version=1))
    store.save(aggregate(version=2))
    store.active_path.write_text("activo roto", encoding="utf-8")
    store.backup_path.write_text("copia rota", encoding="utf-8")
    before = store.active_path.read_bytes()

    result = store.load()
    assert result.status is LoadStatus.BLOCKED
    assert result.data is None
    assert store.active_path.read_bytes() == before
    assert result.quarantine_path
    assert Path(result.quarantine_path).exists()


def test_corrupt_active_without_backup_blocks_and_quarantines(store):
    store.active_path.parent.mkdir(parents=True)
    store.active_path.write_text("roto", encoding="utf-8")
    result = store.load()
    assert result.status is LoadStatus.BLOCKED
    assert Path(result.quarantine_path).exists()
    assert store.active_path.read_text(encoding="utf-8") == "roto"
