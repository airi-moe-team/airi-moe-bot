"""Migración segura desde los seis JSON heredados (tarea 3.2)."""

from __future__ import annotations

import json

from airi.adapters.state_store import StateStore
from airi.services.migration import LegacyMigrator, MigrationStatus

LEGACY = {
    "world.json": {"season": 2, "winner_id": None},
    "affinity.json": {"1": {"points": 12, "milestones": []}},
    "dates.json": {},
    "diary.json": [{"kind": "meet", "text": "hola"}],
    "memories.json": {"1": ["recuerdo"]},
    "users.json": {"1": {"name": "Ana", "interactions": 3}},
}


def write_legacy(data_dir, overrides=None):
    data = dict(LEGACY)
    if overrides:
        data.update(overrides)
    for name, payload in data.items():
        (data_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )


def test_full_migration_preserves_values_and_originals(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_legacy(data_dir)
    originals = {p.name: p.read_bytes() for p in data_dir.glob("*.json")}
    store = StateStore(data_dir)
    result = LegacyMigrator(data_dir, store).run()

    assert result.status is MigrationStatus.MIGRATED
    assert result.backup_dir
    assert result.source_hash
    active = json.loads(store.active_path.read_text(encoding="utf-8"))
    assert active["world"]["season"] == 2
    assert active["affinity"]["1"]["points"] == 12
    assert active["diary"] == [{"kind": "meet", "text": "hola"}]
    assert active["histories"] == {}
    assert active["turn_records"] == {}
    assert active["schema_version"] == 1
    for name, content in originals.items():
        assert (data_dir / name).read_bytes() == content
    assert (data_dir / "migration.json").exists()


def test_second_run_is_idempotent(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_legacy(data_dir)
    store = StateStore(data_dir)
    migrator = LegacyMigrator(data_dir, store)
    first = migrator.run()
    second = migrator.run()
    assert first.status is MigrationStatus.MIGRATED
    assert second.status is MigrationStatus.ALREADY_MIGRATED
    assert second.source_hash == first.source_hash


def test_no_legacy_files_is_not_an_error(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    result = LegacyMigrator(data_dir, StateStore(data_dir)).run()
    assert result.status is MigrationStatus.NO_SOURCE


def test_partial_legacy_set_blocks_without_creating_state(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "world.json").write_text('{"season": 1}', encoding="utf-8")
    result = LegacyMigrator(data_dir, StateStore(data_dir)).run()
    assert result.status is MigrationStatus.BLOCKED
    assert not (data_dir / "state.json").exists()


def test_corrupt_optional_histories_blocks(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_legacy(data_dir)
    (data_dir / "histories.json").write_text("{roto", encoding="utf-8")
    result = LegacyMigrator(data_dir, StateStore(data_dir)).run()
    assert result.status is MigrationStatus.BLOCKED
    assert not (data_dir / "state.json").exists()


def test_corrupt_legacy_file_blocks_and_quarantines(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_legacy(data_dir)
    (data_dir / "diary.json").write_text("{roto", encoding="utf-8")
    result = LegacyMigrator(data_dir, StateStore(data_dir)).run()
    assert result.status is MigrationStatus.BLOCKED
    assert result.quarantine_dir
    assert not (data_dir / "state.json").exists()
    quarantined = list((data_dir / "quarantine").iterdir())
    assert quarantined
