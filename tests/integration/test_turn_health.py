"""Tests del health check desacoplado del flujo de conversación (`turn.py`).

El pre-chequeo por perfil no debe bloquear los perfiles remotos: un fallo de
`GET /v1/models` degrada a warning y el turno se intenta igual. El perfil
`llama` conserva el fallo duro histórico sobre `/health`.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import aiohttp
import pytest

from airi.discord_bot import turn as turn_module
from airi.discord_bot.context import BotContext
from airi.testing import make_state

# --- Dobles ----------------------------------------------------------------


class _Resp:
    def __init__(self, status):
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=self.status,
                message="err",
            )

    async def text(self):
        return ""

    async def json(self):
        return {}


class _Ctx:
    def __init__(self, status):
        self._status = status

    async def __aenter__(self):
        return _Resp(self._status)

    async def __aexit__(self, *exc_info):
        return False


class _FakeClientSession:
    """Sustituto de `aiohttp.ClientSession` que registra las peticiones GET."""

    instances = []
    health_status = 200

    def __init__(self, *args, **kwargs):
        self.get_calls = []
        _FakeClientSession.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def get(self, url, timeout=None):
        self.get_calls.append(url)
        return _Ctx(_FakeClientSession.health_status)


class _FakeService:
    def __init__(self):
        self.called = False

    async def run_turn(self, author, messages, turn_context):
        self.called = True
        # `skipped=True` corta el turno justo después del health check.
        return SimpleNamespace(trace=None, skipped=True)


class _FakeChannel:
    id = 7

    def __init__(self):
        self.sent = []

    def typing(self):
        class _T:
            async def __aenter__(self_inner):
                return None

            async def __aexit__(self_inner, *exc_info):
                return False

        return _T()

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


def _ctx(provider="llama", health_enabled=True, service=None):
    state, _ = make_state()
    service = service or _FakeService()
    ctx = BotContext(
        channel_id=7,
        state=state,
        lock=asyncio.Lock(),
        request_timeout=5,
        llama_url="http://backend:8081",
        llm_provider=provider,
        llm_health_check=health_enabled,
        build_service=lambda session, state_, channel: service,
    )
    return ctx, service


def _run_turn(monkeypatch, ctx):
    channel = _FakeChannel()
    author = SimpleNamespace(id=1, display_name="Ana")
    asyncio.run(
        turn_module.run_user_turn(
            ctx, channel, author, [("message", "hola")]
        )
    )
    return channel


@pytest.fixture(autouse=True)
def _fake_session(monkeypatch):
    _FakeClientSession.instances = []
    _FakeClientSession.health_status = 200
    monkeypatch.setattr(turn_module.aiohttp, "ClientSession", _FakeClientSession)
    return _FakeClientSession


# --- Perfil llama ----------------------------------------------------------


def test_llama_turn_pings_root_health(monkeypatch):
    ctx, service = _ctx(provider="llama")
    _run_turn(monkeypatch, ctx)
    assert _FakeClientSession.instances[0].get_calls == ["http://backend:8081/health"]
    assert service.called is True


def test_llama_health_failure_aborts_turn(monkeypatch):
    """Comportamiento histórico: salud KO en local → turno abortado."""
    _FakeClientSession.health_status = 500
    ctx, service = _ctx(provider="llama")
    channel = _run_turn(monkeypatch, ctx)
    assert service.called is False
    assert channel.sent, "debe contestarse el aviso de servicio caído"


# --- Perfiles remotos ------------------------------------------------------


def test_openai_turn_pings_v1_models(monkeypatch):
    ctx, service = _ctx(provider="openai")
    _run_turn(monkeypatch, ctx)
    assert _FakeClientSession.instances[0].get_calls == [
        "http://backend:8081/v1/models"
    ]
    assert service.called is True


def test_remote_health_failure_does_not_block_turn(monkeypatch):
    """¡Clave! Salud KO en API remota → warning y el turno se intenta igual."""
    _FakeClientSession.health_status = 401
    ctx, service = _ctx(provider="openai")
    channel = _run_turn(monkeypatch, ctx)
    assert service.called is True
    assert channel.sent == []


def test_health_check_disabled_makes_no_request(monkeypatch):
    ctx, service = _ctx(provider="openai", health_enabled=False)
    _run_turn(monkeypatch, ctx)
    assert _FakeClientSession.instances[0].get_calls == []
    assert service.called is True


# --- Compatibilidad de BotContext -----------------------------------------


def test_bot_context_defaults_keep_local_profile():
    """Constructores antiguos sin los nuevos campos siguen en perfil llama."""
    state, _ = make_state()
    ctx = BotContext(channel_id=1, state=state)
    assert ctx.llm_provider == "llama"
    assert ctx.llm_health_check is True
