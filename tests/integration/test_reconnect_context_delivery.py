"""El contexto de reconexión se marca entregado solo tras publicar el turno."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from airi.discord_bot import turn as turn_module
from airi.testing import make_state


class _Resp:
    status = 200

    def raise_for_status(self):
        return None


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
        reply="Buenas noches.",
        gif="none",
        gif_bytes=None,
        in_date=False,
        disconnect_reason=None,
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


def _ctx(result, acknowledged):
    state, _ = make_state()

    async def noop(*args, **kwargs):
        return None

    async def acknowledge_reconnect_context():
        acknowledged.append(True)

    return SimpleNamespace(
        state=state,
        channel_id=7,
        request_timeout=5,
        llm_base_url="http://backend:7000",
        build_service=lambda session, state_, channel: _FakeService(result),
        remember_trace=lambda trace: None,
        process_date_turn=noop,
        add_diary_reflection=lambda *args, **kwargs: None,
        affinity_footer=lambda user: "",
        request_shutdown=noop,
        is_shutting_down=lambda: False,
        acknowledge_reconnect_context=acknowledge_reconnect_context,
    )


def _run(result):
    acknowledged = []
    ctx = _ctx(result, acknowledged)
    channel = _FakeChannel()
    author = SimpleNamespace(id=1, display_name="Ana")
    asyncio.run(
        turn_module.run_user_turn(ctx, channel, author, [(author, "hola")])
    )
    return acknowledged


def test_published_turn_marks_reconnect_context_delivered(monkeypatch):
    monkeypatch.setattr(turn_module.aiohttp, "ClientSession", _FakeClientSession)

    assert _run(_result()) == [True]


def test_failed_turn_keeps_reconnect_context_pending(monkeypatch):
    monkeypatch.setattr(turn_module.aiohttp, "ClientSession", _FakeClientSession)

    assert _run(_result(reply="")) == []
