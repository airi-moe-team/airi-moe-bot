"""La capa Discord solicita el cierre después de publicar la despedida."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from airi.discord_bot import turn as turn_module
from airi.observability.trace import TurnEvent
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

    def __init__(self, *, fail_first=False):
        self.sent = []
        self.fail_first = fail_first

    def typing(self):
        class _Typing:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc_info):
                return False

        return _Typing()

    async def send(self, content=None, **kwargs):
        if self.fail_first:
            self.fail_first = False
            raise RuntimeError("fallo de publicación")
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

    async def request_shutdown(reason, user_id=None, correlation_id=None):
        shutdown_calls.append((reason, user_id, correlation_id))

    async def noop(*args, **kwargs):
        return None

    return SimpleNamespace(
        state=state,
        channel_id=7,
        request_timeout=5,
        llm_base_url="http://backend:7000",
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

    assert shutdown_calls == [("me voy a dormir", 1, "")]
    assert any("Buenas noches" in (content or "") for content, _ in channel.sent)


def test_disconnect_trace_records_shutdown_request(monkeypatch):
    monkeypatch.setattr(turn_module.aiohttp, "ClientSession", _FakeClientSession)
    shutdown_calls = []
    trace = TurnEvent(correlation_id="cid-disconnect")
    ctx = _ctx(_result(trace=trace), shutdown_calls)
    channel = _FakeChannel()
    author = SimpleNamespace(id=1, display_name="Ana")

    run(turn_module.run_user_turn(ctx, channel, author, [(author, "vamos a dormir")]))

    assert shutdown_calls == [("me voy a dormir", 1, "cid-disconnect")]
    assert trace.shutdown_request is not None
    assert trace.shutdown_request["origin"] == "model"
    assert trace.shutdown_request["correlation_id"] == "cid-disconnect"
    assert trace.shutdown_request["requested_at"] > 0


def test_no_disconnect_does_not_request_shutdown(monkeypatch):
    monkeypatch.setattr(turn_module.aiohttp, "ClientSession", _FakeClientSession)
    shutdown_calls = []
    ctx = _ctx(_result(disconnect_reason=None), shutdown_calls)
    channel = _FakeChannel()
    author = SimpleNamespace(id=1, display_name="Ana")

    run(turn_module.run_user_turn(ctx, channel, author, [(author, "hola")]))

    assert shutdown_calls == []


def test_personal_farewell_does_not_request_global_shutdown(monkeypatch):
    monkeypatch.setattr(turn_module.aiohttp, "ClientSession", _FakeClientSession)
    shutdown_calls = []
    ctx = _ctx(
        _result(reply="Hasta luego, cuídate.", disconnect_reason=None),
        shutdown_calls,
    )
    channel = _FakeChannel()
    author = SimpleNamespace(id=1, display_name="Ana")

    run(
        turn_module.run_user_turn(
            ctx, channel, author, [(author, "me voy, hasta luego")]
        )
    )

    assert shutdown_calls == []


def test_publication_failure_does_not_request_shutdown(monkeypatch):
    monkeypatch.setattr(turn_module.aiohttp, "ClientSession", _FakeClientSession)
    shutdown_calls = []
    ctx = _ctx(_result(), shutdown_calls)
    channel = _FakeChannel(fail_first=True)
    author = SimpleNamespace(id=1, display_name="Ana")

    run(turn_module.run_user_turn(ctx, channel, author, [(author, "vamos a dormir")]))

    assert shutdown_calls == []
