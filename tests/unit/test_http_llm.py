"""Tests de `airi.adapters.http_llm.HttpLlmClient`."""

import asyncio
import json
import logging
from unittest.mock import MagicMock

import aiohttp
import pytest

from airi.adapters import http_llm
from airi.adapters.http_llm import DEFAULT_MAX_OUTPUT_TOKENS, HttpLlmClient
from airi.ports.llm import LLMCallContext, PayloadCaptureResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    """Elimina variables LLM del entorno para cada test."""
    for key in (
        "LLM_MODEL",
        "LLM_TIMEOUT",
        "LLM_MAX_TOKENS",
        "LLM_PROVIDER",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "LLM_MAX_TOKENS_FIELD",
        "LLM_RESPONSE_FORMAT",
        "LLM_HEALTH_CHECK",
        "LLM_THINKING_MODE",
        "LLM_REASONING_BUDGET_LOW_TOKENS",
        "LLM_REASONING_BUDGET_MEDIUM_TOKENS",
        "LLM_REASONING_BUDGET_HIGH_TOKENS",
        "LLM_REASONING_OUTPUT_RESERVE_TOKENS",
        "AIRI_TRACE_LLM_PAYLOAD_DIR",
        "TRACE_LLM_PAYLOAD_DIR",
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


def _make_async_session(response_data=None):
    """Sesión doble con `post` que captura el payload."""
    session = MagicMock()

    class _Resp:
        async def json(self):
            return response_data or {"choices": [{"message": {"content": "hi"}}]}

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


def _make_streaming_session(chunks):
    """Sesión que entrega bloques arbitrarios de un event-stream SSE."""
    session = MagicMock()

    class _Content:
        async def iter_any(self):
            for chunk in chunks:
                yield chunk

    class _Resp:
        status = 200
        content = _Content()

        def raise_for_status(self):
            pass

    class _PostCtx:
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
        )
    )
    payload = session._captured
    assert payload["max_tokens"] == 1234


def test_chat_with_meta_is_non_streaming_by_default():
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:7000", session=session)

    run(client.chat_with_meta([{"role": "user", "content": "hola"}]))

    assert session._captured["stream"] is False


def test_native_tool_calls_are_sent_and_parsed():
    session = _make_async_session({
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "buscar_web",
                        "arguments": '{"query":"precio bitcoin","motivo":"curiosidad"}',
                    },
                }],
            },
        }],
    })
    client = HttpLlmClient(base_url="http://localhost:7000", session=session)
    tools = [{"type": "function", "function": {"name": "buscar_web"}}]

    content, meta = run(client.chat_with_meta(
        [{"role": "user", "content": "precio BTC"}],
        tools=tools,
        tool_choice="auto",
    ))

    assert content == ""
    assert session._captured["tools"] == tools
    assert session._captured["tool_choice"] == "auto"
    assert "response_format" not in session._captured
    assert meta.finish_reason == "tool_calls"
    assert meta.tool_calls == [{
        "id": "call-1",
        "name": "buscar_web",
        "arguments": {"query": "precio bitcoin", "motivo": "curiosidad"},
    }]


def test_native_tools_reject_schema_and_streaming():
    client = HttpLlmClient(
        base_url="http://localhost:7000", session=_make_async_session()
    )
    messages = [{"role": "user", "content": "hola"}]

    with pytest.raises(ValueError, match="tools y response_format"):
        run(client.chat_with_meta(messages, tools=[{}], schema={"type": "object"}))
    with pytest.raises(ValueError, match="tools no está soportado en streaming"):
        run(client.chat_with_meta(messages, tools=[{}], stream=True))


def test_non_stream_response_preserves_reasoning_presence_and_server_timings(tmp_path):
    from airi.observability.llm_payload_capture import LocalLlmPayloadCapture, load_llm_response
    from airi.ports.llm import LLMCallContext

    session = _make_async_session({
        "choices": [{"message": {
            "content": '{"reply":"hola"}',
            "reasoning_content": "no persistir reasoning",
        }, "finish_reason": "stop"}],
        "usage": {
            "completion_tokens": 8,
            "completion_tokens_details": {"reasoning_tokens": 4},
        },
        "timings": {"prompt_ms": 12.5, "predicted_ms": 30, "ignored": "x"},
    })
    capture = LocalLlmPayloadCapture(tmp_path)
    context = LLMCallContext("reasoning-nonstream", "primary", 1)
    client = HttpLlmClient(base_url="http://localhost:7000", session=session,
                           payload_capture=capture)

    content, meta = run(client.chat_with_meta([{"role": "user", "content": "hola"}],
                                              call_context=context))

    assert content == '{"reply":"hola"}'
    assert meta.reasoning_present is True
    assert meta.reasoning_tokens == 4
    assert meta.reasoning_budget_tokens is None
    assert meta.server_timings == {"prompt_ms": 12.5, "predicted_ms": 30}
    output = load_llm_response(
        capture.base_dir / context.response_capture.artifact_ref,
        correlation_id=context.correlation_id, call_index=1,
        sha256=context.response_capture.sha256,
    )
    assert output["content"] == content
    assert output["reasoning_content"] == "no persistir reasoning"
    assert meta.ttft_ms is None


def test_non_stream_response_without_reasoning_omits_optional_artifact_field(tmp_path):
    from airi.observability.llm_payload_capture import LocalLlmPayloadCapture, load_llm_response
    from airi.ports.llm import LLMCallContext

    session = _make_async_session({"choices": [{"message": {"content": "visible"}}]})
    capture = LocalLlmPayloadCapture(tmp_path)
    context = LLMCallContext("without-reasoning", "primary", 1)
    client = HttpLlmClient("http://localhost:7000", session, payload_capture=capture)

    run(client.chat_with_meta([], call_context=context))
    output = load_llm_response(
        tmp_path / context.response_capture.artifact_ref,
        correlation_id=context.correlation_id, call_index=1,
        sha256=context.response_capture.sha256,
    )

    assert "reasoning_content" not in output


def test_streaming_chat_collects_content_ttft_and_optional_metadata(monkeypatch):
    session = _make_streaming_session([
        b'data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{"reasoning_content":"pensando"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"{\\"reply\\":"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"\\"hola\\"}"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":8,"total_tokens":20,"completion_tokens_details":{"reasoning_tokens":4}},"timings":{"prompt_ms":11.5,"predicted_ms":20.0,"prompt_n":12,"predicted_n":8}}\n\n',
        b"data: [DONE]\n\n",
    ])
    client = HttpLlmClient(base_url="http://localhost:7000", session=session)
    ticks = iter((10.0, 10.05, 10.20))
    monkeypatch.setattr(http_llm.time, "perf_counter", lambda: next(ticks))

    content, meta = run(
        client.chat_with_meta(
            [{"role": "user", "content": "hola"}],
            schema={"type": "object"},
            strict_schema=True,
            stream=True,
        )
    )

    assert content == '{"reply":"hola"}'
    assert session._captured["stream"] is True
    assert meta.ttft_ms == 50
    assert meta.first_content_ms == 200
    assert meta.reasoning_present is True
    assert meta.reasoning_tokens == 4
    assert meta.server_timings["prompt_ms"] == 11.5
    assert meta.usage["prompt_tokens"] == 12


def test_streaming_captures_assembled_response_not_sse():
    from airi.ports.llm import LLMCallContext, PayloadCaptureResult

    class Capture:
        async def capture(self, context, payload):
            return PayloadCaptureResult("captured", "request", "a" * 64)

        async def capture_response(self, context, output):
            self.output = output
            return PayloadCaptureResult("captured", "response", "b" * 64)

    capture = Capture()
    session = _make_streaming_session([
        b'data: {"choices":[{"delta":{"reasoning_content":"think-1"}}]}\n\n',
        b'data: {"choices":[{"delta":{"reasoning_content":"think-2"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"second"},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ])
    context = LLMCallContext("cid", "primary", 1)
    client = HttpLlmClient("http://localhost:7000", session, payload_capture=capture)

    content, _ = run(client.chat_with_meta([{"role": "user", "content": "x"}],
                                           stream=True, call_context=context))

    assert content == "firstsecond"
    assert capture.output["content"] == content
    assert capture.output["reasoning_content"] == "think-1think-2"
    assert context.response_capture.artifact_ref == "response"


def test_streaming_sse_parser_accepts_fragmented_network_chunks():
    session = _make_streaming_session([
        b'data: {"choices":[{"delta":{"content":"hel',
        b'lo"},"finish_reason":null}]}\n\ndata: [DO',
        b'NE]\n\n',
    ])
    client = HttpLlmClient(base_url="http://localhost:7000", session=session)

    content, meta = run(
        client.chat_with_meta(
            [{"role": "user", "content": "hola"}], stream=True
        )
    )

    assert content == "hello"
    assert meta.finish_reason is None
    assert meta.ttft_ms is not None


def test_streaming_missing_done_fails_instead_of_silent_fallback():
    session = _make_streaming_session([
        b'data: {"choices":[{"delta":{"content":"respuesta"},"finish_reason":null}]}\n\n'
    ])
    client = HttpLlmClient(base_url="http://localhost:7000", session=session)

    with pytest.raises(ValueError, match="SSE"):
        run(client.chat_with_meta([{"role": "user", "content": "hola"}], stream=True))


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
    run(client.chat_with_meta([{"role": "user", "content": "hi"}]))
    assert session._captured_headers == {"Authorization": "Bearer sk-test-123"}


def test_post_omits_headers_without_api_key():
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    run(client.chat_with_meta([{"role": "user", "content": "hi"}]))
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


def test_profile_llama_sends_reasoning_budget_and_never_disables(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, reasoning_budget_tokens=256)
    assert session._captured["thinking_budget_tokens"] == 256
    assert session._captured["chat_template_kwargs"] == {"enable_thinking": True}
    assert "reasoning_effort" not in session._captured


@pytest.mark.parametrize("mode,budget", [("low", 256), ("medium", 1024), ("high", 4096)])
def test_global_budget_is_recorded_in_response_metadata(monkeypatch, mode, budget):
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    session = _make_async_session()
    client = HttpLlmClient(
        base_url="http://localhost:8080", session=session, thinking_mode=mode
    )

    _content, meta = run(
        client.chat_with_meta([{"role": "user", "content": "hola"}])
    )

    assert meta.reasoning_budget_tokens == budget


@pytest.mark.parametrize(
    "mode,budget",
    [("low", 256), ("medium", 1024), ("high", 4096)],
)
def test_output_cap_reserves_tokens_after_reasoning_budget(monkeypatch, mode, budget):
    monkeypatch.setenv("LLM_REASONING_OUTPUT_RESERVE_TOKENS", "1")
    monkeypatch.setenv(f"LLM_REASONING_BUDGET_{mode.upper()}_TOKENS", "999")
    session = _make_async_session()
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=session,
        thinking_mode=mode,
        max_output_tokens=400,
    )

    _chat(client)

    assert session._captured["thinking_budget_tokens"] == budget
    assert session._captured["max_tokens"] == budget + 512
    assert session._captured["max_tokens"] >= budget + 512


def test_profile_openai_omits_chat_template_kwargs(monkeypatch):
    """Fuera del perfil `llama` no se envía el campo propietario de llama.cpp."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.openai.com/v1", session=session)
    _chat(client, reasoning_budget_tokens=256)
    assert "chat_template_kwargs" not in session._captured
    assert "thinking_budget_tokens" not in session._captured


def test_profile_openai_compatible_omits_chat_template_kwargs(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.groq.com/openai/v1", session=session)
    _chat(client, reasoning_budget_tokens=256)
    assert "chat_template_kwargs" not in session._captured
    assert "thinking_budget_tokens" not in session._captured


# ---------------------------------------------------------------------------
# Modo de razonamiento: LLM_THINKING_MODE (auto|low|medium|high)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["auto", None])
def test_thinking_mode_default_is_auto(monkeypatch, mode):
    if mode is None:
        monkeypatch.delenv("LLM_THINKING_MODE", raising=False)
    else:
        monkeypatch.setenv("LLM_THINKING_MODE", mode)
    client = HttpLlmClient(base_url="http://localhost:8080", session=_make_session())
    assert client.thinking_mode == "auto"


@pytest.mark.parametrize("mode", ["auto", "low", "medium", "high", "AUTO", " LOW "])
def test_reads_llm_thinking_mode_from_env(monkeypatch, mode):
    monkeypatch.setenv("LLM_THINKING_MODE", mode)
    client = HttpLlmClient(base_url="http://localhost:8080", session=_make_session())
    expected = mode.strip().lower()
    assert client.thinking_mode == expected


@pytest.mark.parametrize("value", ["abc", "2", "off", "on"])
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


@pytest.mark.parametrize("mode", ["low", "medium", "high"])
def test_budget_modes_keep_reasoning_on_quick_turns(monkeypatch, mode):
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    monkeypatch.setenv("LLM_THINKING_MODE", mode)
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, quick_turn=True)
    assert session._captured["chat_template_kwargs"] == {"enable_thinking": True}
    expected = {"low": 256, "medium": 1024, "high": 4096}.get(mode)
    if expected is None:
        assert "thinking_budget_tokens" not in session._captured
    else:
        assert session._captured["thinking_budget_tokens"] == expected


@pytest.mark.parametrize("mode", ["auto", "low", "medium", "high"])
@pytest.mark.parametrize("stream", [False, True])
def test_explicit_repair_budget_overrides_global_per_call(
    monkeypatch, mode, stream
):
    monkeypatch.setenv("LLM_THINKING_MODE", mode)
    session = (
        _make_streaming_session([b"data: [DONE]\n\n"])
        if stream
        else _make_async_session()
    )
    client = HttpLlmClient(
        base_url="http://localhost:7000", session=session, thinking_mode=mode
    )

    run(client.chat_with_meta(
        [{"role": "user", "content": "repair"}],
        reasoning_budget_tokens=256,
        quick_turn=True,
        stream=stream,
    ))

    assert session._captured["thinking_budget_tokens"] == 256
    assert session._captured["chat_template_kwargs"] == {"enable_thinking": True}


def test_auto_mode_keeps_reasoning_active_even_for_quick_turns(monkeypatch):
    monkeypatch.setenv("LLM_THINKING_MODE", "auto")
    session = _make_async_session()
    client = HttpLlmClient(
        base_url="http://localhost:7000", session=session, thinking_mode="auto"
    )

    run(client.chat_with_meta(
        [{"role": "user", "content": "primary"}],
        quick_turn=True,
    ))

    assert session._captured["chat_template_kwargs"] == {"enable_thinking": True}
    assert session._captured["thinking_budget_tokens"] == 256


def test_reasoning_budget_is_not_sent_to_non_llama_profile():
    session = _make_async_session()
    client = HttpLlmClient(
        base_url="http://localhost:7000",
        session=session,
        provider="openai-compatible",
        thinking_mode="auto",
    )

    run(client.chat_with_meta(
        [{"role": "user", "content": "repair"}],
        reasoning_budget_tokens=256,
    ))

    assert "chat_template_kwargs" not in session._captured


def test_thinking_mode_auto_keeps_reasoning_on_quick_turns_with_low_budget(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    monkeypatch.setenv("LLM_THINKING_MODE", "auto")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, quick_turn=True)
    assert session._captured["chat_template_kwargs"] == {"enable_thinking": True}
    assert session._captured["thinking_budget_tokens"] == 256


def test_thinking_mode_auto_normal_turn_uses_server_budget(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    monkeypatch.setenv("LLM_THINKING_MODE", "auto")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, quick_turn=False)
    assert session._captured["chat_template_kwargs"] == {"enable_thinking": True}
    assert "thinking_budget_tokens" not in session._captured


@pytest.mark.parametrize("mode,expected", [("low", 256), ("medium", 1024), ("high", 4096)])
def test_reasoning_presets_ignore_legacy_budget_environment(monkeypatch, mode, expected):
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    monkeypatch.setenv("LLM_THINKING_MODE", mode)
    monkeypatch.setenv("LLM_REASONING_BUDGET_LOW_TOKENS", "999")
    monkeypatch.setenv("LLM_REASONING_BUDGET_MEDIUM_TOKENS", "999")
    monkeypatch.setenv("LLM_REASONING_BUDGET_HIGH_TOKENS", "999")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)

    _chat(client)

    assert session._captured["thinking_budget_tokens"] == expected


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_invalid_per_call_budget_fails_before_http(monkeypatch, budget):
    client = HttpLlmClient(
        base_url="http://localhost:8080", session=_make_async_session(),
        thinking_mode="auto",
    )
    with pytest.raises(ValueError, match="reasoning_budget_tokens"):
        _chat(client, reasoning_budget_tokens=budget)


def test_explicit_thinking_mode_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_THINKING_MODE", "low")
    client = HttpLlmClient(
        base_url="http://localhost:8080",
        session=_make_session(),
        thinking_mode="high",
    )
    assert client.thinking_mode == "high"


def test_profile_llama_uses_max_tokens_field(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "llama")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client)
    assert session._captured["max_tokens"] == client.max_output_tokens
    assert "max_completion_tokens" not in session._captured


def test_profile_openai_uses_max_completion_tokens(monkeypatch):
    """Perfil `openai`: default del campo de salida `max_completion_tokens`."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.openai.com/v1", session=session)
    _chat(client)
    assert session._captured["max_completion_tokens"] == client.max_output_tokens
    assert "max_tokens" not in session._captured


def test_profile_openai_compatible_uses_max_tokens(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://openrouter.ai/api/v1", session=session)
    _chat(client)
    assert session._captured["max_tokens"] == client.max_output_tokens
    assert "max_completion_tokens" not in session._captured


def test_max_tokens_field_env_overrides_profile_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MAX_TOKENS_FIELD", "max_tokens")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.openai.com/v1", session=session)
    _chat(client)
    assert session._captured["max_tokens"] == client.max_output_tokens
    assert "max_completion_tokens" not in session._captured


def test_temperature_is_always_delegated_to_provider(monkeypatch):
    """Variables heredadas no controlan temperatura ni alteran el payload."""
    monkeypatch.setenv("LLM_SKIP_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.15")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.openai.com/v1", session=session)
    _chat(client)
    assert "temperature" not in session._captured
    assert not hasattr(client, "temperature")
    assert not hasattr(client, "skip_temperature")


def test_post_strips_temperature_from_caller_payload():
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)

    run(client.post({"messages": [], "temperature": 0.1}))

    assert "temperature" not in session._captured


def test_response_format_disabled_by_env(monkeypatch):
    monkeypatch.setenv("LLM_RESPONSE_FORMAT", "0")
    session = _make_async_session()
    client = HttpLlmClient(base_url="http://localhost:8080", session=session)
    _chat(client, schema={"type": "object"}, strict_schema=True)
    assert "response_format" not in session._captured


def test_response_format_strict_json_schema(monkeypatch):
    """El perfil `openai` admite `json_schema` estricto (igual que llama.cpp)."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    session = _make_async_session()
    client = HttpLlmClient(base_url="https://api.openai.com/v1", session=session)
    _chat(
        client,
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


# ---------------------------------------------------------------------------
# Conteo de deltas y solicitud de `usage` en streaming (metadatos por llamada)
# ---------------------------------------------------------------------------


def test_streaming_counts_reasoning_and_content_deltas():
    session = _make_streaming_session([
        b'data: {"choices":[{"delta":{"reasoning_content":"a"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{"reasoning_content":"b"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{"reasoning_content":"c"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"{1}"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"{2}"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ])
    client = HttpLlmClient(base_url="http://localhost:7000", session=session)

    _content, meta = run(
        client.chat_with_meta([{"role": "user", "content": "hola"}], stream=True)
    )

    assert meta.reasoning_deltas == 3
    assert meta.content_deltas == 2


def test_reasoning_budget_is_returned_in_streaming_metadata():
    session = _make_streaming_session([b"data: [DONE]\n\n"])
    client = HttpLlmClient(
        base_url="http://localhost:7000", session=session, thinking_mode="medium"
    )

    _content, meta = run(
        client.chat_with_meta([{"role": "user", "content": "hola"}], stream=True)
    )

    assert session._captured["thinking_budget_tokens"] == 1024
    assert meta.reasoning_budget_tokens == 1024


def test_streaming_payload_requests_usage_for_llama_profile():
    session = _make_streaming_session([b"data: [DONE]\n\n"])
    client = HttpLlmClient(base_url="http://localhost:7000", session=session)

    run(client.chat_with_meta([{"role": "user", "content": "hola"}], stream=True))

    assert session._captured["stream_options"] == {"include_usage": True}


def test_streaming_payload_omits_usage_request_for_openai_compatible():
    session = _make_streaming_session([b"data: [DONE]\n\n"])
    client = HttpLlmClient(
        base_url="http://localhost:7000",
        session=session,
        provider="openai-compatible",
        thinking_mode="auto",
    )

    run(client.chat_with_meta([{"role": "user", "content": "hola"}], stream=True))

    assert "stream_options" not in session._captured


def test_non_streaming_response_has_no_delta_counts():
    session = _make_async_session({
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
    })
    client = HttpLlmClient(base_url="http://localhost:7000", session=session)

    _content, meta = run(client.chat_with_meta([{"role": "user", "content": "hola"}]))

    assert meta.reasoning_deltas is None
    assert meta.content_deltas is None


def test_payload_capture_matches_effective_non_streaming_post_body():
    class Capture:
        def __init__(self):
            self.payload = None

        async def capture(self, context, payload):
            self.payload = json.loads(json.dumps(payload))
            return PayloadCaptureResult(
                status="captured", artifact_ref="cid/call.json", sha256="abc"
            )

    session = _make_async_session()
    capture = Capture()
    client = HttpLlmClient(
        base_url="http://localhost:7000",
        session=session,
        api_key="top-secret-header-only",
        payload_capture=capture,
    )
    context = LLMCallContext("cid", "primary", 1)

    _content, meta = run(client.chat_with_meta(
        [{"role": "user", "content": "exact prompt"}],
        strict_schema=True,
        schema={"type": "object"},
        call_context=context,
    ))

    assert capture.payload == session._captured
    assert capture.payload["model"] == client.model
    assert capture.payload["response_format"]["json_schema"]["strict"] is True
    assert "top-secret-header-only" not in json.dumps(capture.payload)
    assert meta.payload_capture.artifact_ref == "cid/call.json"
    assert context.payload_capture.status == "captured"


def test_streaming_capture_failure_does_not_block_post():
    class BrokenCapture:
        async def capture(self, context, payload):
            raise OSError("secret content must not escape")

    session = _make_streaming_session([b"data: [DONE]\n\n"])
    context = LLMCallContext("cid", "primary", 1)
    client = HttpLlmClient(
        base_url="http://localhost:7000", session=session,
        payload_capture=BrokenCapture(),
    )

    _content, meta = run(client.chat_with_meta(
        [{"role": "user", "content": "prompt"}],
        stream=True,
        call_context=context,
    ))

    assert session._captured["stream"] is True
    assert context.payload_capture.status == "failed"
    assert context.payload_capture.error == "OSError"
    assert meta.payload_capture.status == "failed"


def test_build_llm_payload_capture_is_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv("AIRI_TRACE_LLM_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("TRACE_LLM_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("AIRI_TRACE_LLM_PAYLOAD_DIR", raising=False)
    monkeypatch.delenv("TRACE_LLM_PAYLOAD_DIR", raising=False)
    without_capture = http_llm.build_llm(_make_session())
    assert without_capture.payload_capture is None

    monkeypatch.setenv("TRACE_LLM_PAYLOAD_DIR", str(tmp_path))
    with_capture = http_llm.build_llm(_make_session())
    assert with_capture.payload_capture is not None
    assert with_capture.payload_capture.base_dir == tmp_path

    preferred_dir = tmp_path / "preferred"
    monkeypatch.setenv("AIRI_TRACE_LLM_PAYLOAD_DIR", str(preferred_dir))
    preferred = http_llm.build_llm(_make_session())
    assert preferred.payload_capture.base_dir == preferred_dir

    new_dir = tmp_path / "new-name"
    monkeypatch.setenv("TRACE_LLM_ARTIFACTS_DIR", str(new_dir))
    monkeypatch.delenv("AIRI_TRACE_LLM_PAYLOAD_DIR", raising=False)
    new_name = http_llm.build_llm(_make_session())
    assert new_name.payload_capture.base_dir == new_dir

    canonical_dir = tmp_path / "canonical"
    monkeypatch.setenv("AIRI_TRACE_LLM_ARTIFACTS_DIR", str(canonical_dir))
    canonical = http_llm.build_llm(_make_session())
    assert canonical.payload_capture.base_dir == canonical_dir
