"""Arranque: carga, migración o defaults sin sobrescribir datos (tarea 3.3)."""

from __future__ import annotations

import json

import pytest

from airi.adapters.state_store import StateStore
from airi.services.bootstrap import BootstrapError, bootstrap_state
from airi.services.migration import LegacyMigrator


def write_legacy(data_dir):
    legacy = {
        "world.json": {"season": 3},
        "affinity.json": {},
        "dates.json": {},
        "diary.json": [],
        "memories.json": {},
        "users.json": {},
    }
    for name, payload in legacy.items():
        (data_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def run_bootstrap(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = StateStore(data_dir)
    return bootstrap_state(
        store=store,
        migrator=LegacyMigrator(data_dir, store),
    )


def test_new_install_uses_defaults(tmp_path):
    result = run_bootstrap(tmp_path)
    assert result.state.world["season"] == 1
    assert result.state.state_version == 0
    assert result.migration is None


def test_complete_legacy_migrates_at_startup(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_legacy(data_dir)
    store = StateStore(data_dir)
    result = bootstrap_state(store=store, migrator=LegacyMigrator(data_dir, store))
    assert result.state.world["season"] == 3
    assert result.migration is not None
    assert result.migration.status.value == "migrated"
    assert store.active_path.exists()


def test_corrupt_legacy_blocks_startup(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_legacy(data_dir)
    (data_dir / "diary.json").write_text("{roto", encoding="utf-8")
    store = StateStore(data_dir)
    with pytest.raises(BootstrapError):
        bootstrap_state(store=store, migrator=LegacyMigrator(data_dir, store))


def test_corrupt_active_with_valid_backup_recovers(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = StateStore(data_dir)
    from airi.services.bootstrap import bootstrap_state as boot

    first = boot(store=store, migrator=LegacyMigrator(data_dir, store))
    first.persistence.save()
    first.state.world["season"] = 2
    first.persistence.save()
    store.active_path.write_text("{roto", encoding="utf-8")
    result = boot(store=store, migrator=LegacyMigrator(data_dir, store))
    assert result.state.world["season"] == 1
    assert result.recovered is True
