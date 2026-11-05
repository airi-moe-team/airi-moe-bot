"""Pruebas del estado conversacional activo durante el arranque."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from airi.discord_bot import client as client_module
from airi.discord_bot.spectator_timers import arm_active_timer
from airi.services.spectator_session import (
    ConversationState,
    SpectatorSessionRegistry,
)

CHANNEL_ID = 7


class FakeUser:
    def __init__(self, user_id=99):
        self.id = user_id
        self.bot = False
        self.display_name = "persona"


class FakeMessage:
    def __init__(self, message_id, content, created_at, *, author=None):
        self.id = message_id
        self.content = content
        self.created_at = created_at
        self.author = author or FakeUser(101)
        self.attachments = []


class FakeChannel:
    def __init__(self, messages=None, channel_id=CHANNEL_ID):
        self.id = channel_id
        self._messages = list(messages or [])

    async def history(self, limit=50):
        for message in self._messages[:limit]:
            yield message


class FakeClient:
    def __init__(self, channel, *, user=None, tracker=None):
        self._channel = channel
        self.user = user or FakeUser(99)
        self._pending_message_tracker = tracker

    def get_channel(self, _channel_id):
        return self._channel

    async def fetch_channel(self, _channel_id):
        return self._channel


class FakeDispatcher:
    def __init__(self):
        self.jobs = []

    async def submit(self, channel_id, job):
        self.jobs.append((channel_id, job))
        await job()


class EnabledPolicy:
    enabled = True


def _build_ctx(channel, tracker=None):
    return SimpleNamespace(channel_id=channel.id, tracker=tracker)


async def _cancel_timers(timers):
    tasks = [task for task in timers.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _seed(client, session, *, timers, dispatcher, run_turn=None, policy=None):
    await client_module.seed_last_human_activity(
        client,
        channel_id=CHANNEL_ID,
        session=session,
        build_ctx=_build_ctx,
        timers=timers,
        dispatcher=dispatcher,
        run_turn=run_turn,
        policy_loader=lambda: policy or EnabledPolicy(),
        clock=lambda: 1000.0,
    )


def test_arranque_sin_pendiente_entra_en_activa_y_arma_ventana():
    async def scenario():
        session = SpectatorSessionRegistry(
            clock=lambda: 1000.0, active_idle_seconds=300.0
        )
        timers = {}
        dispatcher = FakeDispatcher()
        client = FakeClient(FakeChannel([]))
        try:
            await _seed(client, session, timers=timers, dispatcher=dispatcher)
            assert session.state(CHANNEL_ID) == ConversationState.ACTIVE
            assert (str(CHANNEL_ID), "active") in timers
            assert session.session(CHANNEL_ID).last_human_activity == 1000.0
        finally:
            await _cancel_timers(timers)

    asyncio.run(scenario())


def test_arranque_sin_pendiente_respeta_ventana_cero():
    async def scenario():
        session = SpectatorSessionRegistry(
            clock=lambda: 1000.0, active_idle_seconds=0.0
        )
        timers = {}
        client = FakeClient(FakeChannel([]))
        await _seed(client, session, timers=timers, dispatcher=FakeDispatcher())
        assert session.state(CHANNEL_ID) == ConversationState.SPECTATING
        assert timers == {}

    asyncio.run(scenario())


def test_arranque_con_politica_desactivada_no_activa():
    async def scenario():
        session = SpectatorSessionRegistry(
            clock=lambda: 1000.0, active_idle_seconds=300.0
        )
        timers = {}
        client = FakeClient(FakeChannel([]))
        await _seed(
            client,
            session,
            timers=timers,
            dispatcher=FakeDispatcher(),
            policy=SimpleNamespace(enabled=False),
        )
        assert session.state(CHANNEL_ID) == ConversationState.SPECTATING
        assert timers == {}

    asyncio.run(scenario())


def test_arranque_con_pendiente_responde_en_modo_activo():
    async def scenario():
        session = SpectatorSessionRegistry(
            clock=lambda: 1000.0, active_idle_seconds=300.0
        )
        timers = {}
        dispatcher = FakeDispatcher()
        message = FakeMessage("1", "hola", 990.0)
        client = FakeClient(FakeChannel([message]))
        calls = []

        async def run_turn(ctx, channel, author, merged, **kwargs):
            calls.append((ctx, channel, author, merged, kwargs))

        try:
            await _seed(
                client,
                session,
                timers=timers,
                dispatcher=dispatcher,
                run_turn=run_turn,
            )
            assert len(calls) == 1
            assert calls[0][4]["kind"] == "active"
            assert calls[0][4]["reply_target"] is message
            assert session.state(CHANNEL_ID) == ConversationState.ACTIVE
            assert (str(CHANNEL_ID), "active") in timers
        finally:
            await _cancel_timers(timers)

    asyncio.run(scenario())


def test_arranque_con_pendiente_que_se_retira_no_deja_timer():
    async def scenario():
        session = SpectatorSessionRegistry(
            clock=lambda: 1000.0, active_idle_seconds=300.0
        )
        timers = {}
        message = FakeMessage("1", "hola", 990.0)
        client = FakeClient(FakeChannel([message]))

        async def run_turn(ctx, channel, author, merged, **kwargs):
            session.finish_active_turn(
                channel.id, stay_active=False, published=True
            )

        await _seed(
            client,
            session,
            timers=timers,
            dispatcher=FakeDispatcher(),
            run_turn=run_turn,
        )
        assert session.state(CHANNEL_ID) == ConversationState.SPECTATING
        assert timers == {}

    asyncio.run(scenario())


def test_arranque_con_pendiente_que_falla_deja_timer_de_respaldo():
    async def scenario():
        session = SpectatorSessionRegistry(
            clock=lambda: 1000.0, active_idle_seconds=300.0
        )
        timers = {}
        message = FakeMessage("1", "hola", 990.0)
        client = FakeClient(FakeChannel([message]))

        async def run_turn(*args, **kwargs):
            raise RuntimeError("boom")

        try:
            await _seed(
                client,
                session,
                timers=timers,
                dispatcher=FakeDispatcher(),
                run_turn=run_turn,
            )
            assert session.state(CHANNEL_ID) == ConversationState.ACTIVE
            assert (str(CHANNEL_ID), "active") in timers
        finally:
            await _cancel_timers(timers)

    asyncio.run(scenario())


def test_arranque_sin_canal_resoluble_activa_igualmente():
    async def scenario():
        session = SpectatorSessionRegistry(
            clock=lambda: 1000.0, active_idle_seconds=300.0
        )
        timers = {}
        client = FakeClient(None)
        try:
            await _seed(client, session, timers=timers, dispatcher=FakeDispatcher())
            assert session.state(CHANNEL_ID) == ConversationState.ACTIVE
            assert (str(CHANNEL_ID), "active") in timers
        finally:
            await _cancel_timers(timers)

    asyncio.run(scenario())


class RetireRegistry:
    active_idle_seconds = 0.01

    def __init__(self):
        self.retired = []

    def session(self, channel_id):
        return SimpleNamespace(generation=3)

    def retire_if_idle(self, channel_id, generation, now, timeout):
        self.retired.append((channel_id, generation, timeout))
        return True


def test_arm_active_timer_retira_al_vencer():
    async def scenario():
        registry = RetireRegistry()
        timers = {}
        dispatcher = FakeDispatcher()
        assert arm_active_timer(
            registry=registry,
            timers=timers,
            dispatcher=dispatcher,
            channel_id=CHANNEL_ID,
            timeout=0.01,
        )
        await asyncio.sleep(0.05)
        assert registry.retired
        assert registry.retired[0][0] == CHANNEL_ID
        assert registry.retired[0][1] == 3
        assert dispatcher.jobs

    asyncio.run(scenario())


def test_arm_active_timer_deshabilitado_con_cero():
    registry = RetireRegistry()
    timers = {}
    assert (
        arm_active_timer(
            registry=registry,
            timers=timers,
            dispatcher=FakeDispatcher(),
            channel_id=CHANNEL_ID,
            timeout=0,
        )
        is False
    )
    assert timers == {}
