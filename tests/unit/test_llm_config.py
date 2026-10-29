"""Tests de `LlmConfig`, `build_llm` y las utilidades de URL del adaptador LLM.

Cubre la configuración por variables de entorno (perfil `llama` por defecto,
alias histórico `OPENAI_API_KEY`) y la fábrica única que usan los
tres puntos de construcción del cliente en el bot.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import aiohttp
import pytest

from airi.adapters.http_llm import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    HttpLlmClient,
    LlmConfig,
    build_llm,
    chat_completions_url,
    health_check,
    health_check_url,
)

ENV_KEYS = (
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "LLM_MODEL",
    "LLM_MAX_TOKENS_FIELD",
    "LLM_SKIP_TEMPERATURE",
    "LLM_RESPONSE_FORMAT",
    "LLM_HEALTH_CHECK",
    "LLM_THINKING_MODE",
    "LLM_TIMEOUT",
    "LLM_MAX_TOKENS",
    "LLM_TEMPERATURE",
)


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _make_session():
    return MagicMock()


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# LlmConfig.from_env
# ---------------------------------------------------------------------------


def test_config_defaults_are_llama_profile():
    cfg = LlmConfig.from_env()
    assert cfg.provider == "llama"
    assert cfg.base_url == DEFAULT_BASE_URL
    assert cfg.api_key == ""
    assert cfg.model == DEFAULT_MODEL
    assert cfg.max_tokens_field == "max_tokens"
    assert cfg.skip_temperature is False
    assert cfg.response_format is True
    assert cfg.health_check is True


def test_config_openai_profile_default_field(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    cfg = LlmConfig.from_env()
    assert cfg.provider == "openai"
    assert cfg.max_tokens_field == "max_completion_tokens"


def test_config_thinking_mode_default_is_auto():
    cfg = LlmConfig.from_env()
    assert cfg.thinking_mode == "auto"


def test_config_reads_thinking_mode(monkeypatch):
    monkeypatch.setenv("LLM_THINKING_MODE", "medium")
    cfg = LlmConfig.from_env()
    assert cfg.thinking_mode == "medium"


def test_config_rejects_off_and_falls_back_to_auto(monkeypatch):
    monkeypatch.setenv("LLM_THINKING_MODE", "off")
    assert LlmConfig.from_env().thinking_mode == "auto"


def test_config_invalid_thinking_mode_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_THINKING_MODE", "siempre")
    cfg = LlmConfig.from_env()
    assert cfg.thinking_mode == "auto"


def test_build_llm_propagates_thinking_mode(monkeypatch):
    monkeypatch.setenv("LLM_THINKING_MODE", "on")
    client = build_llm(_make_session())
    assert client.thinking_mode == "on"


def test_config_openai_compatible_profile_default_field(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    cfg = LlmConfig.from_env()
    assert cfg.provider == "openai-compatible"
    assert cfg.max_tokens_field == "max_tokens"


def test_config_max_tokens_field_env_wins(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MAX_TOKENS_FIELD", "max_tokens")
    assert LlmConfig.from_env().max_tokens_field == "max_tokens"


def test_config_invalid_provider_falls_back_to_llama(monkeypatch, caplog):
    monkeypatch.setenv("LLM_PROVIDER", "groq-cualquiera")
    with caplog.at_level(logging.WARNING, logger="airi.adapters.http_llm"):
        cfg = LlmConfig.from_env()
    assert cfg.provider == "llama"


def test_config_base_url_from_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    assert LlmConfig.from_env().base_url == "https://api.openai.com/v1"


def test_config_api_key_from_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-direct")
    assert LlmConfig.from_env().api_key == "sk-direct"


def test_config_api_key_alias_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-alias")
    assert LlmConfig.from_env().api_key == "sk-alias"


def test_config_model_from_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    assert LlmConfig.from_env().model == "gpt-4o-mini"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", True),
        ("0", False),
        ("true", True),
        ("false", False),
        ("yes", True),
        ("no", False),
    ],
)
def test_config_boolean_flags(raw, expected, monkeypatch):
    monkeypatch.setenv("LLM_SKIP_TEMPERATURE", raw)
    monkeypatch.setenv("LLM_RESPONSE_FORMAT", raw)
    monkeypatch.setenv("LLM_HEALTH_CHECK", raw)
    cfg = LlmConfig.from_env()
    assert cfg.skip_temperature is expected
    assert cfg.response_format is expected
    assert cfg.health_check is expected


def test_config_empty_flags_mean_defaults(monkeypatch):
    """Flag vacía (`VAR=`) = sin definir → default de cada flag."""
    monkeypatch.setenv("LLM_SKIP_TEMPERATURE", "")
    monkeypatch.setenv("LLM_RESPONSE_FORMAT", "")
    monkeypatch.setenv("LLM_HEALTH_CHECK", "")
    cfg = LlmConfig.from_env()
    assert cfg.skip_temperature is False
    assert cfg.response_format is True
    assert cfg.health_check is True


# ---------------------------------------------------------------------------
# build_llm (fábrica única)
# ---------------------------------------------------------------------------


def test_build_llm_uses_env_config(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-abc")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    client = build_llm(_make_session(), timeout=42)
    assert isinstance(client, HttpLlmClient)
    assert client.provider == "openai"
    assert client.base_url == "https://api.openai.com/v1"
    assert client.api_key == "sk-abc"
    assert client.model == "gpt-4o-mini"
    assert client.timeout == 42
    assert client.max_tokens_field == "max_completion_tokens"


def test_build_llm_defaults_to_llama_profile():
    client = build_llm(_make_session())
    assert client.provider == "llama"
    assert client.base_url == DEFAULT_BASE_URL
    assert client.api_key == ""
    assert client.max_tokens_field == "max_tokens"


def test_build_llm_base_url_override():
    """El `base_url` explícito (glue, tests) pisa el del entorno."""
    client = build_llm(_make_session(), base_url="http://x")
    assert client.base_url == "http://x"


# ---------------------------------------------------------------------------
# URL de chat por perfil (compatibilidad con llama-server y APIs /v1)
# ---------------------------------------------------------------------------


def test_chat_url_appends_v1():
    assert (
        chat_completions_url("http://127.0.0.1:8081")
        == "http://127.0.0.1:8081/v1/chat/completions"
    )


def test_chat_url_keeps_existing_v1():
    assert (
        chat_completions_url("https://api.openai.com/v1/")
        == "https://api.openai.com/v1/chat/completions"
    )


# ---------------------------------------------------------------------------
# health_check (Fase 4): comportamiento por perfil
# ---------------------------------------------------------------------------


def _get_session(status=200, exc=None):
    """Sesión falsa con `get` que registra la URL y devuelve `status`."""
    session = MagicMock()

    class _Resp:
        def __init__(self):
            self.status = status

        def raise_for_status(self):
            if status >= 400:
                raise aiohttp.ClientResponseError(
                    request_info=MagicMock(),
                    history=(),
                    status=status,
                    message="err",
                )

        async def text(self):
            return ""

        async def json(self):
            return {}

    class _Ctx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *exc_info):
            return False

    def get(url, timeout=None):
        session.captured_url = url
        if exc is not None:
            raise exc
        return _Ctx()

    session.get = get
    session.get_calls = []
    original_get = get

    def counting_get(url, timeout=None):
        session.get_calls.append(url)
        return original_get(url, timeout=timeout)

    session.get = counting_get
    return session


def test_health_check_url_llama_root():
    assert health_check_url("llama", "http://127.0.0.1:8081") == "http://127.0.0.1:8081/health"


def test_health_check_url_llama_strips_v1():
    """llama-server expone /health en la raíz, nunca bajo /v1."""
    assert health_check_url("llama", "http://127.0.0.1:8080/v1") == "http://127.0.0.1:8080/health"


def test_health_check_url_openai_full():
    assert (
        health_check_url("openai", "https://api.openai.com/v1")
        == "https://api.openai.com/v1/models"
    )


def test_health_check_url_openai_without_v1():
    assert (
        health_check_url("openai", "https://api.openai.com")
        == "https://api.openai.com/v1/models"
    )


def test_health_disabled_makes_no_request():
    session = _get_session()
    ok = run(
        health_check(
            session, provider="llama", base_url="http://x", enabled=False
        )
    )
    assert ok is True
    assert session.get_calls == []


def test_health_llama_ok():
    session = _get_session()
    ok = run(health_check(session, provider="llama", base_url="http://x"))
    assert ok is True
    assert session.captured_url == "http://x/health"


def test_health_llama_http_error_propagates():
    """Perfil local: el fallo se propaga (comportamiento histórico)."""
    session = _get_session(status=500)
    with pytest.raises(aiohttp.ClientResponseError):
        run(health_check(session, provider="llama", base_url="http://x"))


def test_health_llama_connection_error_propagates():
    session = _get_session(exc=aiohttp.ClientConnectionError("down"))
    with pytest.raises(aiohttp.ClientConnectionError):
        run(health_check(session, provider="llama", base_url="http://x"))


def test_health_remote_ok():
    session = _get_session()
    ok = run(
        health_check(
            session, provider="openai", base_url="https://api.openai.com/v1"
        )
    )
    assert ok is True
    assert session.captured_url == "https://api.openai.com/v1/models"


def test_health_remote_http_error_does_not_block(caplog):
    """Perfil remoto: HTTP 4xx/5xx → warning + False (el turno continúa)."""
    session = _get_session(status=401)
    with caplog.at_level(logging.WARNING, logger="airi.adapters.http_llm"):
        ok = run(
            health_check(
                session, provider="openai", base_url="https://api.openai.com/v1"
            )
        )
    assert ok is False
    assert "HTTP 401" in caplog.text
    assert "continúa" in caplog.text


def test_health_remote_connection_error_does_not_block(caplog):
    session = _get_session(exc=aiohttp.ClientConnectionError("down"))
    with caplog.at_level(logging.WARNING, logger="airi.adapters.http_llm"):
        ok = run(
            health_check(
                session, provider="openai-compatible", base_url="https://x/v1"
            )
        )
    assert ok is False
    assert "inaccesible" in caplog.text
