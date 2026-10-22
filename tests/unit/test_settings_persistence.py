"""Configuración de persistencia y retención (tarea 2.4)."""

from __future__ import annotations

from airi.config import Settings

_NAMES = (
    "AIRI_DATA_DIR",
    "DATA_DIR",
    "AIRI_BACKUP_RETENTION",
    "AIRI_SEASON_RETENTION",
    "AIRI_PUBLISH_TTL_SECONDS",
    "AIRI_TURN_RETENTION_SECONDS",
)


def _clear(monkeypatch):
    for name in _NAMES:
        monkeypatch.delenv(name, raising=False)


def test_persistence_defaults(monkeypatch):
    _clear(monkeypatch)
    settings = Settings.from_env()
    assert settings.data_dir == "data"
    assert settings.backup_retention == 5
    assert settings.season_retention == 3
    assert settings.publish_ttl_seconds == 900
    assert settings.turn_retention_seconds == 7 * 24 * 3600


def test_persistence_reads_airi_names(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AIRI_DATA_DIR", "/tmp/airi-data")
    monkeypatch.setenv("AIRI_BACKUP_RETENTION", "8")
    monkeypatch.setenv("AIRI_SEASON_RETENTION", "4")
    monkeypatch.setenv("AIRI_PUBLISH_TTL_SECONDS", "120")
    monkeypatch.setenv("AIRI_TURN_RETENTION_SECONDS", "3600")
    settings = Settings.from_env()
    assert settings.data_dir == "/tmp/airi-data"
    assert settings.backup_retention == 8
    assert settings.season_retention == 4
    assert settings.publish_ttl_seconds == 120
    assert settings.turn_retention_seconds == 3600


def test_invalid_persistence_values_use_defaults(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AIRI_BACKUP_RETENTION", "no")
    monkeypatch.setenv("AIRI_SEASON_RETENTION", "no")
    monkeypatch.setenv("AIRI_PUBLISH_TTL_SECONDS", "no")
    monkeypatch.setenv("AIRI_TURN_RETENTION_SECONDS", "no")
    settings = Settings.from_env()
    assert settings.backup_retention == 5
    assert settings.season_retention == 3
    assert settings.publish_ttl_seconds == 900
    assert settings.turn_retention_seconds == 7 * 24 * 3600
