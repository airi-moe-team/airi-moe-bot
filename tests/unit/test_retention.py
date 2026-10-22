"""Retención acotada de temporadas y copias (tarea 4.2)."""

from __future__ import annotations

import json

from airi.services.retention import RetentionService


def make_season(root, number):
    target = root / "archive" / "seasons" / str(number)
    target.mkdir(parents=True)
    (target / "state.json").write_text(json.dumps({"season": number}), encoding="utf-8")


def make_backup(root, name):
    target = root / "backups" / name
    target.mkdir(parents=True)
    (target / "world.json").write_text("{}", encoding="utf-8")


def test_keeps_only_newest_seasons_and_backups(tmp_path):
    for number in range(1, 6):
        make_season(tmp_path, number)
    for index in range(1, 5):
        make_backup(tmp_path, f"pre-aggregate-2026010{index}T000000")

    report = RetentionService(
        tmp_path, season_limit=2, backup_limit=2
    ).prune()

    kept = sorted(p.name for p in (tmp_path / "archive" / "seasons").iterdir())
    backups = sorted(p.name for p in (tmp_path / "backups").iterdir())
    assert kept == ["4", "5"]
    assert backups == [
        "pre-aggregate-20260103T000000",
        "pre-aggregate-20260104T000000",
    ]
    assert len(report.removed_seasons) == 3
    assert len(report.removed_backups) == 2


def test_protected_active_artifacts_are_never_removed(tmp_path):
    (tmp_path / "state.json").write_text("{}", encoding="utf-8")
    (tmp_path / "state.json.bak").write_text("{}", encoding="utf-8")
    (tmp_path / "migration.json").write_text("{}", encoding="utf-8")
    make_season(tmp_path, 1)
    make_backup(tmp_path, "pre-aggregate-old")

    RetentionService(tmp_path, season_limit=0, backup_limit=0).prune()

    assert (tmp_path / "state.json").exists()
    assert (tmp_path / "state.json.bak").exists()
    assert (tmp_path / "migration.json").exists()


def test_prune_is_idempotent(tmp_path):
    for number in range(1, 4):
        make_season(tmp_path, number)
    service = RetentionService(tmp_path, season_limit=1, backup_limit=1)
    first = service.prune()
    second = service.prune()
    assert first.removed_seasons
    assert second.removed_seasons == []
    assert second.removed_backups == []
