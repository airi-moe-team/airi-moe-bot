"""Tests de `airi.adapters.http_llm.HttpLlmClient`."""

import asyncio
import json
import logging
from unittest.mock import MagicMock

import aiohttp
import pytest

from airi.adapters.http_llm import DEFAULT_MAX_OUTPUT_TOKENS, HttpLlmClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    """Elimina variables LLM del entorno para cada test."""
    for key in (
        "LLM_MODEL",
        "LLM_TIMEOUT",
        "LLM_TEMPERATURE",
        "LLM_MAX_TOKENS",
        "LLM_PROVIDER",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "LLM_MAX_TOKENS_FIELD",
        "LLM_SKIP_TEMPERATURE",
        "LLM_RESPONSE_FORMAT",
        "LLM_HEALTH_CHECK",
        "LLM_THINKING_MODE",
    ):
        monkeypatch.delenv(key, raising=False)


def _make_session():
    """Devuelve un objeto falso con el atributo `post`."""
    return MagicMock()


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Valores por defecto (sin variables de entorno)
# ---------------------------------------------------------------------------


def test_defaults_no_env():
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
    )
    assert client.model == "Qwen3.6-35B-A3B-MTP-UD-IQ3_S"
    assert client.timeout == 300
    assert client.temperature == 0.6
    assert client.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS


# ---------------------------------------------------------------------------
# Lectura desde variables de entorno
# ---------------------------------------------------------------------------


def test_reads_llm_model_from_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "MiModelo")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
    )
    assert client.model == "MiModelo"


def test_reads_llm_timeout_from_env(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "600")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
    )
    assert client.timeout == 600


def test_reads_llm_temperature_from_env(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "0.85")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
    )
    assert client.temperature == 0.85


def test_reads_llm_max_tokens_from_env(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
    )
    assert client.max_output_tokens == 4096


# ---------------------------------------------------------------------------
# Valores inválidos en env → fallback a default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["abc", "", "   ", "1.2.3"])
def test_invalid_timeout_fallback(monkeypatch, value):
    monkeypatch.setenv("LLM_TIMEOUT", value)
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
    )
    assert client.timeout == 300


@pytest.mark.parametrize("value", ["abc", "", "   ", "xyz"])
def test_invalid_temperature_fallback(monkeypatch, value):
    monkeypatch.setenv("LLM_TEMPERATURE", value)
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
    )
    assert client.temperature == 0.6


@pytest.mark.parametrize("value", ["abc", "", "   ", "1.2.3"])
def test_invalid_max_tokens_fallback(monkeypatch, value):
    monkeypatch.setenv("LLM_MAX_TOKENS", value)
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
    )
    assert client.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS


# ---------------------------------------------------------------------------
# Prioridad: explícito > env > default
# ---------------------------------------------------------------------------


def test_explicit_model_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "DelEnv")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
        model="Explicito",
    )
    assert client.model == "Explicito"


def test_explicit_timeout_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "999")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
        timeout=120,
    )
    assert client.timeout == 120


def test_explicit_temperature_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "0.1")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
        temperature=0.95,
    )
    assert client.temperature == 0.95


def test_explicit_max_tokens_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "9999")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
        max_output_tokens=512,
    )
    assert client.max_output_tokens == 512


def test_none_explicit_uses_env(monkeypatch):
    """`timeout=None` (valor por defecto) debe respetar la variable de entorno."""
    monkeypatch.setenv("LLM_TIMEOUT", "420")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
        timeout=None,
    )
    assert client.timeout == 420


def test_none_explicit_uses_env_temperature(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "0.42")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
        temperature=None,
    )
    assert client.temperature == 0.42


def test_none_explicit_uses_env_max_tokens(monkeypatch):
    """`max_output_tokens=None` (por defecto) debe respetar LLM_MAX_TOKENS."""
    monkeypatch.setenv("LLM_MAX_TOKENS", "777")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
        max_output_tokens=None,
    )
    assert client.max_output_tokens == 777


# ---------------------------------------------------------------------------
# Payload: `max_tokens` en la petición usa el valor correcto
# ---------------------------------------------------------------------------


def _make_async_session():
    """Sesión doble con `post` que captura el payload."""
    session = MagicMock()

    class _Resp:
        async def json(self):
            return {"choices": [{"message": {"content": "hi"}}]}

        def raise_for_status(self):
            pass

    class _PostCtx:
        def __init__(self):
            self._captured = None

        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *exc_info):
            return False

    def fake_post(url, json=None, timeout=None, headers=None):
        session._captured = json
        session._captured_url = url
        session._captured_headers = headers
        return _PostCtx()

    session.post = fake_post
    session._captured_url = None
    session._captured_headers = None
    return session


def test_payload_uses_max_output_tokens():
    """Verifica que `chat_with_meta` envía `max_tokens` correcto en el payload."""
    session = _make_async_session()
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=session,
        max_output_tokens=1234,
    )
    run(
        client.chat_with_meta(
            [{"role": "user", "content": "hi"}],
            temperature=0.5,
        )
    )
    payload = session._captured
    assert payload["max_tokens"] == 1234


def test_payload_explicit_max_tokens_overrides_adapter():
    """`max_tokens` explícito en el payload pisa el valor del adapter."""
    session = _make_async_session()
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=session,
        max_output_tokens=9999,
    )
    run(
        client.chat_with_meta(
            [{"role": "user", "content": "hi"}],
            max_tokens=42,
            temperature=0.5,
        )
    )
    payload = session._captured
    assert payload["max_tokens"] == 42


def test_payload_max_tokens_zero_uses_adapter():
    """`max_tokens=0` (truthy-falsy) usa el valor del adapter por `or`."""
    session = _make_async_session()
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=session,
        max_output_tokens=500,
    )
    run(
        client.chat_with_meta(
            [{"role": "user", "content": "hi"}],
            max_tokens=0,
            temperature=0.5,
        )
    )
    payload = session._captured
    assert payload["max_tokens"] == 500


def test_payload_llm_max_tokens_minus_one_is_unlimited(monkeypatch):
    """LLM_MAX_TOKENS=-1 → payload["max_tokens"] == -1 (ilimitado)."""
    monkeypatch.setenv("LLM_MAX_TOKENS", "-1")
    session = _make_async_session()
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=session,
    )
    run(
        client.chat_with_meta(
            [{"role": "user", "content": "hi"}],
            temperature=0.5,
        )
    )
    payload = session._captured
    assert payload["max_tokens"] == -1


def test_payload_llm_max_tokens_zero_is_no_output(monkeypatch):
    """LLM_MAX_TOKENS=0 → payload["max_tokens"] == 0.

    Footgun: en llama.cpp, max_tokens=0 produce respuesta vacía.
    El usuario que quiera sin límite debe usar -1.
    """
    monkeypatch.setenv("LLM_MAX_TOKENS", "0")
    session = _make_async_session()
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=session,
    )
    run(
        client.chat_with_meta(
            [{"role": "user", "content": "hi"}],
            temperature=0.5,
        )
    )
    payload = session._captured
    assert payload["max_tokens"] == 0


# ---------------------------------------------------------------------------
# Autenticación (APIs remotas) y normalización de URL
# ---------------------------------------------------------------------------


def test_post_sends_bearer_header_when_api_key():
    session = _make_async_session()
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=session,
        api_key="sk-test-123",
    )
    run(client.chat_with_meta([{"role": "user", "content": "hi"}], temperature=0.5))
    assert session._captured_headers == {"Authorization": "Bearer sk-test-123"}


def test_post_omits_headers_without_api_key():
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    run(client.chat_with_meta([{"role": "user", "content": "hi"}], temperature=0.5))
    assert session._captured_headers is None


def test_post_url_appends_v1_when_base_has_none():
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    run(client.chat_with_meta([{"role": "user", "content": "hi"}]))
    assert session._captured_url == "http://localhost:8080/v1/chat/completions"


def test_post_url_does_not_duplicate_v1():
    """Bases que ya incluyen `/v1` (OpenAI, OpenRouter...) no la duplican."""
    session = _make_async_session()
    client = HttpLlmClient(
        base_url="https://api.openai.com/v1/", session=session, api_key="sk-x"
    )
    run(client.chat_with_meta([{"role": "user", "content": "hi"}]))
    assert session._captured_url == "https://api.openai.com/v1/chat/completions"


# ---------------------------------------------------------------------------
# Perfiles de proveedor: diferencias de payload
# ---------------------------------------------------------------------------


def _chat(client, **kwargs):
    return run(client.chat_with_meta([{"role": "user", "content": "hi"}], **kwargs))


def test_profile_llama_sends_chat_template_kwargs(monkeypatch):
    """Perfil `llama`: `disable_thinking` se traduce a chat_template_kwargs."""
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, temperature=0.5, disable_thinking=True)
    assert session._captured["chat_template_kwargs"] == {"enable_thinking": False}


def test_profile_openai_omits_chat_template_kwargs(monkeypatch):
    """Fuera del perfil `llama` no se envía el campo propietario de llama.cpp."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.openai.com/v1", session=session)
    _chat(client, temperature=0.5, disable_thinking=True)
    assert "chat_template_kwargs" not in session._captured


def test_profile_openai_compatible_omits_chat_template_kwargs(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.groq.com/openai/v1", session=session)
    _chat(client, disable_thinking=True)
    assert "chat_template_kwargs" not in session._captured


# ---------------------------------------------------------------------------
# Modo de razonamiento: LLM_THINKING_MODE (auto|on|off)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["auto", None])
def test_thinking_mode_default_is_auto(monkeypatch, mode):
    if mode is None:
        monkeypatch.delenv("LLM_THINKING_MODE", raising=False)
    else:
        monkeypatch.setenv("LLM_THINKING_MODE", mode)
    client = HttpLlmClient(base_url="http://localhost:8080", session=_make_session())
    assert client.thinking_mode == "auto"


@pytest.mark.parametrize("mode", ["on", "off", "AUTO", " On "])
def test_reads_llm_thinking_mode_from_env(monkeypatch, mode):
    monkeypatch.setenv("LLM_THINKING_MODE", mode)
    client = HttpLlmClient(base_url="http://localhost:8080", session=_make_session())
    assert client.thinking_mode == mode.strip().lower()


@pytest.mark.parametrize("value", ["abc", "2"])
def test_invalid_thinking_mode_fallback(monkeypatch, value, caplog):
    monkeypatch.setenv("LLM_THINKING_MODE", value)
    with caplog.at_level(logging.WARNING):
        client = HttpLlmClient(
            base_url="http://localhost:8080", session=_make_session()
        )
    assert client.thinking_mode == "auto"
    assert any("LLM_THINKING_MODE" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_thinking_mode_is_auto_silently(monkeypatch, value):
    """Un valor vacío equivale a no configurar (sin warning)."""
    monkeypatch.setenv("LLM_THINKING_MODE", value)
    client = HttpLlmClient(base_url="http://localhost:8080", session=_make_session())
    assert client.thinking_mode == "auto"


@pytest.mark.parametrize("requested", [True, False])
def test_thinking_mode_on_forces_reasoning_even_for_quick_turns(monkeypatch, requested):
    """`on`: nunca se envía chat_template_kwargs, pidan lo que pidan los servicios."""
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    monkeypatch.setenv("LLM_THINKING_MODE", "on")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, disable_thinking=requested)
    assert "chat_template_kwargs" not in session._captured


@pytest.mark.parametrize("requested", [True, False])
def test_thinking_mode_off_disables_reasoning_in_all_turns(monkeypatch, requested):
    """`off`: chat_template_kwargs siempre presente en el perfil `llama`."""
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    monkeypatch.setenv("LLM_THINKING_MODE", "off")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, disable_thinking=requested)
    assert session._captured["chat_template_kwargs"] == {"enable_thinking": False}


def test_thinking_mode_auto_keeps_requested_behavior(monkeypatch):
    """`auto`: se respeta lo que pida el servicio (comportamiento histórico)."""
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    monkeypatch.setenv("LLM_THINKING_MODE", "auto")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, disable_thinking=False)
    assert "chat_template_kwargs" not in session._captured


def test_explicit_thinking_mode_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_THINKING_MODE", "off")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
        thinking_mode="on",
    )
    assert client.thinking_mode == "on"


def test_profile_llama_uses_max_tokens_field(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, temperature=0.5)
    assert session._captured["max_tokens"] == client.max_output_tokens
    assert "max_completion_tokens" not in session._captured


def test_profile_openai_uses_max_completion_tokens(monkeypatch):
    """Perfil `openai`: default del campo de salida `max_completion_tokens`."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.openai.com/v1", session=session)
    _chat(client, temperature=0.5)
    assert session._captured["max_completion_tokens"] == client.max_output_tokens
    assert "max_tokens" not in session._captured


def test_profile_openai_compatible_uses_max_tokens(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://openrouter.ai/api/v1", session=session)
    _chat(client, temperature=0.5)
    assert session._captured["max_tokens"] == client.max_output_tokens
    assert "max_completion_tokens" not in session._captured


def test_max_tokens_field_env_overrides_profile_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MAX_TOKENS_FIELD", "max_tokens")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.openai.com/v1", session=session)
    _chat(client, temperature=0.5)
    assert session._captured["max_tokens"] == client.max_output_tokens
    assert "max_completion_tokens" not in session._captured


def test_skip_temperature_omits_field_entirely(monkeypatch):
    """LLM_SKIP_TEMPERATURE=1 → ni el default ni el explícito se envían."""
    monkeypatch.setenv("LLM_SKIP_TEMPERATURE", "1")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.openai.com/v1", session=session)
    _chat(client, temperature=0.9)
    assert "temperature" not in session._captured


def test_temperature_sent_by_default(monkeypatch):
    monkeypatch.setenv("LLM_SKIP_TEMPERATURE", "0")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, temperature=0.9)
    assert session._captured["temperature"] == 0.9


def test_response_format_disabled_by_env(monkeypatch):
    monkeypatch.setenv("LLM_RESPONSE_FORMAT", "0")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, temperature=0.5, schema={"type": "object"}, strict_schema=True)
    assert "response_format" not in session._captured


def test_response_format_strict_json_schema(monkeypatch):
    """El perfil `openai` admite `json_schema` estricto (igual que llama.cpp)."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.openai.com/v1", session=session)
    _chat(
        client,
        temperature=0.5,
        schema={"type": "object", "properties": {}},
        strict_schema=True,
    )
    rf = session._captured["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True


# ---------------------------------------------------------------------------
# Errores HTTP: código + mensaje útil del proveedor, sin secretos
# ---------------------------------------------------------------------------


def _make_error_session(status, body_text):
    """Sesión cuya respuesta devuelve `status` y lanza en `raise_for_status`."""
    session = MagicMock()

    class _ErrResp:
        def __init__(self):
            self.status = status

        async def text(self):
            return body_text

        async def json(self):
            return {}

        def raise_for_status(self):
            raise aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=status,
                message="error",
            )

    class _Ctx:
        async def __aenter__(self):
            return _ErrResp()

        async def __aexit__(self, *exc_info):
            return False

    session.post = lambda url, json=None, timeout=None, headers=None: _Ctx()
    return session


def test_post_error_logs_status_and_provider_message(caplog):
    body = json.dumps(
        {
            "error": {
                "message": "Invalid API key provided",
                "type": "invalid_request_error",
            }
        }
    )
    session = _make_error_session(401, body)
    client = HttpLlmClient(
        base_url="https://api.openai.com/v1", session=session, api_key="sk-secret-xyz"
    )
    with caplog.at_level(logging.ERROR, logger="airi.adapters.http_llm"):
        with pytest.raises(aiohttp.ClientResponseError):
            run(client.chat_with_meta([{"role": "user", "content": "hi"}]))
    assert "HTTP 401" in caplog.text
    assert "Invalid API key provided" in caplog.text


def test_post_error_never_logs_api_key(caplog):
    """Aunque la clave aparezca en el cuerpo (caso patológico), se sanea."""
    body = json.dumps({"error": {"message": "bad key sk-secret-xyz rejected"}})
    session = _make_error_session(403, body)
    client = HttpLlmClient(
        base_url="https://api.openai.com/v1", session=session, api_key="sk-secret-xyz"
    )
    with caplog.at_level(logging.ERROR, logger="airi.adapters.http_llm"):
        with pytest.raises(aiohttp.ClientResponseError):
            run(client.chat_with_meta([{"role": "user", "content": "hi"}]))
    assert "sk-secret-xyz" not in caplog.text
    assert "***" in caplog.text


def test_post_error_truncates_long_bodies(caplog):
    session = _make_error_session(500, "x" * 5000)
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    with caplog.at_level(logging.ERROR, logger="airi.adapters.http_llm"):
        with pytest.raises(aiohttp.ClientResponseError):
            run(client.chat_with_meta([{"role": "user", "content": "hi"}]))
    lines = [record.getMessage() for record in caplog.records]
    assert lines, "no se registró ningún error"
    assert all(len(line) < 600 for line in lines)
