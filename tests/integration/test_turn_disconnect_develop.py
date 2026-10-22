"""La capa Discord solicita el cierre después de publicar la despedida."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from airi.discord_bot import turn as turn_module
from airi.testing import make_state


class _Resp:
    status = 200

    def raise_for_status(self):
        return None

    async def text(self):
        return ""

    async def json(self):
        return {}


class _Ctx:
    async def __aenter__(self):
        return _Resp()

    async def __aexit__(self, *exc_info):
        return False


class _FakeClientSession:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def get(self, url, timeout=None):
        return _Ctx()


class _FakeChannel:
    id = 7

    def __init__(self):
        self.sent = []

    def typing(self):
        class _Typing:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc_info):
                return False

        return _Typing()

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class _FakeService:
    def __init__(self, result):
        self._result = result

    async def run_turn(self, author, messages, turn_context):
        return self._result


def _result(**overrides):
    base = dict(
        trace=None,
        skipped=False,
        reply="Buenas noches, me voy a dormir.",
        gif="none",
        gif_bytes=None,
        in_date=False,
        disconnect_reason="me voy a dormir",
        date_decision="continue",
        date_reason="none",
        last_chance_result="none",
        date_question=None,
        diary_action="none",
        diary_saved=False,
        affinity_delta=0,
        notices=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _ctx(result, shutdown_calls):
    state, _ = make_state()

    async def request_shutdown(reason, user_id=None):
        shutdown_calls.append((reason, user_id))

    async def noop(*args, **kwargs):
        return None

    return SimpleNamespace(
        state=state,
        channel_id=7,
        request_timeout=5,
        llama_url="http://backend:7000",
        build_service=lambda session, state_, channel: _FakeService(result),
        remember_trace=lambda trace: None,
        settle_relationship=noop,
        process_date_turn=noop,
        add_diary_reflection=lambda *args, **kwargs: None,
        affinity_footer=lambda user: "",
        request_shutdown=request_shutdown,
        is_shutting_down=lambda: False,
    )


def run(coro):
    return asyncio.run(coro)


def test_disconnect_requests_global_shutdown(monkeypatch):
    monkeypatch.setattr(turn_module.aiohttp, "ClientSession", _FakeClientSession)
    shutdown_calls = []
    ctx = _ctx(_result(), shutdown_calls)
    channel = _FakeChannel()
    author = SimpleNamespace(id=1, display_name="Ana")

    run(turn_module.run_user_turn(ctx, channel, author, [(author, "vamos a dormir")]))

    assert shutdown_calls == [("me voy a dormir", 1)]
    assert any("Buenas noches" in (content or "") for content, _ in channel.sent)


def test_no_disconnect_does_not_request_shutdown(monkeypatch):
    monkeypatch.setattr(turn_module.aiohttp, "ClientSession", _FakeClientSession)
    shutdown_calls = []
    ctx = _ctx(_result(disconnect_reason=None), shutdown_calls)
    channel = _FakeChannel()
    author = SimpleNamespace(id=1, display_name="Ana")

    run(turn_module.run_user_turn(ctx, channel, author, [(author, "hola")]))

    assert shutdown_calls == []
