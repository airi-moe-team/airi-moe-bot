"""Tests de `airi.config.Settings` (lectura de entorno, sin dependencias)."""

from airi.config import Settings

_ENV_NAMES = (
    "AIRI_TRACE_DIR",
    "TRACE_DIR",
    "AIRI_TRACE_KEEP_LAST",
    "TRACE_KEEP_LAST",
    "AIRI_CONVERSATION_REVIEW",
    "AIRI_WEB_SEARCH",
)


def _clear(monkeypatch):
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_settings_defaults(monkeypatch):
    _clear(monkeypatch)
    settings = Settings.from_env()
    assert settings.trace_dir == ""
    assert settings.trace_keep_last == 500
    assert settings.conversation_review is True


def test_settings_can_disable_conversation_review(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AIRI_CONVERSATION_REVIEW", "false")
    assert Settings.from_env().conversation_review is False


def test_settings_can_disable_web_search(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AIRI_WEB_SEARCH", "false")
    assert Settings.from_env().web_search is False


def test_settings_reads_airi_names(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AIRI_TRACE_DIR", "/tmp/traces")
    monkeypatch.setenv("AIRI_TRACE_KEEP_LAST", "42")
    settings = Settings.from_env()
    assert settings.trace_dir == "/tmp/traces"
    assert settings.trace_keep_last == 42


def test_settings_falls_back_to_legacy_names(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRACE_DIR", "/legacy")
    monkeypatch.setenv("TRACE_KEEP_LAST", "7")
    settings = Settings.from_env()
    assert settings.trace_dir == "/legacy"
    assert settings.trace_keep_last == 7


def test_settings_prefers_airi_over_legacy(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AIRI_TRACE_DIR", "/new")
    monkeypatch.setenv("TRACE_DIR", "/old")
    monkeypatch.setenv("AIRI_TRACE_KEEP_LAST", "9")
    monkeypatch.setenv("TRACE_KEEP_LAST", "1")
    settings = Settings.from_env()
    assert settings.trace_dir == "/new"
    assert settings.trace_keep_last == 9


def test_settings_invalid_keep_last_uses_default(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AIRI_TRACE_KEEP_LAST", "abc")
    settings = Settings.from_env()
    assert settings.trace_keep_last == 500


def test_settings_empty_dir_is_treated_as_off(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AIRI_TRACE_DIR", "   ")
    monkeypatch.setenv("TRACE_DIR", "/fallback")
    settings = Settings.from_env()
    assert settings.trace_dir == "/fallback"
