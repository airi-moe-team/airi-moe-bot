import pytest

from airi.config import Settings


def test_time_settings_default_enabled_with_system_timezone(monkeypatch):
    monkeypatch.delenv("AIRI_TIME_CONTEXT", raising=False)
    monkeypatch.delenv("AIRI_TIMEZONE", raising=False)
    settings = Settings.from_env()
    assert settings.time_context is True
    assert settings.timezone == ""


def test_time_settings_read_env_values(monkeypatch):
    monkeypatch.setenv("AIRI_TIME_CONTEXT", "off")
    monkeypatch.setenv("AIRI_TIMEZONE", "Europe/Madrid")
    settings = Settings.from_env()
    assert settings.time_context is False
    assert settings.timezone == "Europe/Madrid"


def test_time_context_invalid_value_warns_and_uses_default(monkeypatch):
    monkeypatch.setenv("AIRI_TIME_CONTEXT", "sometimes")
    with pytest.warns(UserWarning, match="AIRI_TIME_CONTEXT"):
        settings = Settings.from_env()
    assert settings.time_context is True
