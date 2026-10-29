"""Tests de integración de los perfiles LLM a través del glue de citas.

Verifica el comportamiento extremo a extremo (env → `build_llm` → payload HTTP)
con el perfil `llama` (default, sin regresión respecto al comportamiento
histórico de llama.cpp) y con el perfil `openai`.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from airi.adapters.http_llm import DEFAULT_MAX_OUTPUT_TOKENS
from airi.discord_bot.client import build_date_glue
from airi.testing import make_state

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
    "LLM_MAX_TOKENS",
)

JUDGE_REPLY = json.dumps(
    {
        "reply": "¡gracias!",
        "affinity_delta": 2,
        # Sin motivo la regla de negocio anula el delta: hay que declararlo.
        "affinity_event": "le hace mucha ilusión",
    }
)


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def run(coro):
    return asyncio.run(coro)


def _session():
    """Sesión falsa que captura (url, json, headers) y devuelve el juicio."""
    session = MagicMock()

    class _Resp:
        status = 200

        async def text(self):
            return ""

        async def json(self):
            return {"choices": [{"message": {"content": JUDGE_REPLY}}]}

        def raise_for_status(self):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *exc_info):
            return False

    def post(url, json=None, timeout=None, headers=None):
        session.captured_url = url
        session.captured_json = json
        session.captured_headers = headers
        return _Ctx()

    session.post = post
    return session


def _judge(glue, session):
    user = SimpleNamespace(id=1)
    return run(glue.judge_gift(session, "un libro", user))


def _glue(llm_base_url):
    state, _ = make_state()
    return build_date_glue(state, llm_base_url=llm_base_url, request_timeout=5)


# ---------------------------------------------------------------------------
# Perfil llama (default): overrides estructurados usan esfuerzo bajo
# ---------------------------------------------------------------------------


def test_llama_mode_payload_unchanged():
    glue = _glue("http://127.0.0.1:8081")
    session = _session()
    reply, delta, event = _judge(glue, session)
    payload = session.captured_json

    assert session.captured_url == "http://127.0.0.1:8081/v1/chat/completions"
    assert session.captured_headers is None
    assert payload["max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS
    assert "max_completion_tokens" not in payload
    assert payload["temperature"] == 0.7
    assert payload["thinking_budget_tokens"] == 256
    assert payload["chat_template_kwargs"] == {"enable_thinking": True}
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    # El flujo completo devuelve el juicio parseado.
    assert reply == "¡gracias!"
    assert delta == 2


# ---------------------------------------------------------------------------
# Perfil openai: Bearer + max_completion_tokens + sin chat_template_kwargs
# ---------------------------------------------------------------------------


def test_openai_mode_payload(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-openai-test")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    glue = _glue("https://api.openai.com/v1")
    session = _session()
    reply, delta, _event = _judge(glue, session)
    payload = session.captured_json

    assert session.captured_url == "https://api.openai.com/v1/chat/completions"
    assert session.captured_headers == {"Authorization": "Bearer sk-openai-test"}
    assert payload["model"] == "gpt-4o-mini"
    assert payload["max_completion_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS
    assert "max_tokens" not in payload
    assert "chat_template_kwargs" not in payload
    assert payload["temperature"] == 0.7
    assert payload["response_format"]["type"] == "json_schema"
    assert reply == "¡gracias!"
    assert delta == 2
