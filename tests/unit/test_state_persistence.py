"""Fachada transaccional entre AppState y StateStore (tarea 3.1)."""

from __future__ import annotations

import json

import pytest

from airi.adapters.state_store import AtomicWriteError, StateStore
from airi.services.persistence import PersistenceError, SaveKind, StatePersistence
from airi.services.state import AppState


def make_state():
    return AppState(
        world={"season": 1},
        affinity={"1": {"points": 0}},
        dates={},
        memories={},
        diary=[],
        users={"1": {"name": "Ana"}},
        histories={},
    )


def make_persistence(tmp_path):
    store = StateStore(tmp_path / "data")
    state = make_state()
    persistence = StatePersistence(store)
    persistence.bind(state)
    return state, persistence, store


def test_immediate_save_persists_every_dataset(tmp_path):
    state, _, store = make_persistence(tmp_path)
    state.world["season"] = 2
    state.save_world()
    payload = json.loads(store.active_path.read_text(encoding="utf-8"))
    assert payload["world"]["season"] == 2
    assert payload["affinity"] == state.affinity
    assert payload["users"] == state.users
    assert payload["state_version"] == 1


def test_transaction_coalesces_multiple_requests(tmp_path, monkeypatch):
    state, persistence, store = make_persistence(tmp_path)
    calls = []
    original = store.save

    def counting_save(aggregate):
        calls.append(dict(aggregate))
        return original(aggregate)

    monkeypatch.setattr(store, "save", counting_save)
    with persistence.transaction():
        state.world["season"] = 2
        state.save_world()
        state.affinity["1"]["points"] = 5
        state.save_affinity()
        assert not store.active_path.exists()
    assert len(calls) == 1
    assert state.state_version == 1
    assert json.loads(store.active_path.read_text(encoding="utf-8"))["world"]["season"] == 2


def test_metadata_save_does_not_advance_domain_version(tmp_path):
    state, persistence, store = make_persistence(tmp_path)
    state.save_world()
    assert state.state_version == 1
    persistence.save(kind=SaveKind.METADATA)
    assert state.state_version == 1
    payload = json.loads(store.active_path.read_text(encoding="utf-8"))
    assert payload["state_version"] == 1


def test_transaction_rolls_back_memory_on_write_failure(tmp_path, monkeypatch):
    state, persistence, store = make_persistence(tmp_path)
    state.save_world()
    previous_version = state.state_version

    def failing_save(_aggregate):
        raise AtomicWriteError("fallo simulado")

    monkeypatch.setattr(store, "save", failing_save)
    with pytest.raises(PersistenceError):
        with persistence.transaction():
            state.world["season"] = 99
            state.diary.append({"text": "no debe quedar"})
            state.save_world()
    assert state.world["season"] == 1
    assert state.diary == []
    assert state.state_version == previous_version


def test_transaction_restores_memory_on_domain_error(tmp_path):
    state, persistence, _ = make_persistence(tmp_path)
    with pytest.raises(ValueError):
        with persistence.transaction():
            state.world["season"] = 99
            raise ValueError("error de dominio")
    assert state.world["season"] == 1
    assert state.state_version == 0


def test_nested_transaction_is_rejected(tmp_path):
    _, persistence, _ = make_persistence(tmp_path)
    with persistence.transaction():
        with pytest.raises(PersistenceError):
            with persistence.transaction():
                pass


def test_histories_roundtrip_with_integer_channel_keys(tmp_path):
    state, persistence, store = make_persistence(tmp_path)
    state.histories[7] = [{"role": "user", "content": "hola"}]
    state.save_state()

    other = make_state()
    reader = StatePersistence(store)
    reader.bind(other)
    reader.load()
    assert 7 in other.histories
    assert other.histories[7][0]["content"] == "hola"


def test_load_populates_bound_state(tmp_path):
    state, persistence, store = make_persistence(tmp_path)
    state.world["season"] = 7
    state.save_world()

    other = make_state()
    reader = StatePersistence(store)
    reader.bind(other)
    result = reader.load()
    assert result.status.value == "ok"
    assert other.world["season"] == 7
    assert other.state_version == 1
