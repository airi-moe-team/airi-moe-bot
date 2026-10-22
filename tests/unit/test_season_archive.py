"""Archivo de temporada antes del reinicio (tarea 4.1)."""

from __future__ import annotations

import json

import pytest

from airi.services.season_archive import SeasonArchiveError, SeasonArchiver


def aggregate(season=2, version=7):
    return {
        "schema_version": 1,
        "state_version": version,
        "world": {"season": season},
        "affinity": {"1": {"points": 10}},
        "dates": {},
        "memories": {"1": ["recuerdo"]},
        "diary": [{"text": "día"}],
        "users": {"1": {"name": "Ana"}},
        "histories": {},
        "turn_records": {},
        "message_index": {},
    }


def test_archive_writes_state_and_metadata(tmp_path):
    archiver = SeasonArchiver(tmp_path)
    path = archiver.archive(season=2, aggregate=aggregate(season=2))
    target = tmp_path / "archive" / "seasons" / "2"
    assert path == str(target)
    payload = json.loads((target / "state.json").read_text(encoding="utf-8"))
    meta = json.loads((target / "meta.json").read_text(encoding="utf-8"))
    assert payload["world"]["season"] == 2
    assert meta["season"] == 2
    assert meta["state_version"] == 7
    assert meta["archived_at"] > 0


def test_invalid_aggregate_is_rejected(tmp_path):
    with pytest.raises(SeasonArchiveError):
        SeasonArchiver(tmp_path).archive(season=1, aggregate={"world": {}})
    assert not (tmp_path / "archive").exists()


def test_rearchiving_preserves_previous_archive_as_backup(tmp_path):
    archiver = SeasonArchiver(tmp_path)
    archiver.archive(season=2, aggregate=aggregate(season=2, version=1))
    archiver.archive(season=2, aggregate=aggregate(season=2, version=2))
    target = tmp_path / "archive" / "seasons" / "2"
    assert (target / "state.json.bak").exists()
    backup = json.loads((target / "state.json.bak").read_text(encoding="utf-8"))
    assert backup["state_version"] == 1
