"""Pipeline de extremo a extremo del modo espectador (sin red ni Discord real)."""

import asyncio
import logging
from contextlib import contextmanager

import pytest

from airi.discord_bot import client as client_module
from airi.services.conversation import ConversationService
from airi.services.state import AppState
from airi.testing import FakeGif, FakeLLM, FakeNotifier, FakeSearch, llm_json

AIRI_ID = 2026
DEBOUNCE = 0.02


class FakeTyping:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return None


class FakeChannel:
    id = 7

    def __init__(self):
        self.sent = []

    def typing(self):
        return FakeTyping()

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        sent = getattr(self, "on_sent", None)
        if sent is not None:
            sent()


class FakePersistence:
    def __init__(self):
        return

    @contextmanager
    def transaction(self):
        yield


class FakeMessage:
    def __init__(self, author, content, channel, *, mid=1000, reference=None):
        self.author = author
        self.content = content
        self.channel = channel
        self.id = mid
        self.reference = reference
        self.attachments = []


class FakeClient:
    instances = []

    def __init__(self, *, intents):
        self.events = {}
        self.closed = False
        self._channel = None
        FakeClient.instances.append(self)

    def event(self, fn):
        self.events[fn.__name__] = fn
        return fn

    async def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed

    def get_channel(self, _id):
        return self._channel


def _writer_reply():
    return llm_json("Ramens siempre, cuenta conmigo", affinity_delta=0)


@pytest.fixture
def service_llm():
    llm = FakeLLM(default_reply=_writer_reply())
    return llm


def _setup(monkeypatch, llm, *, enabled):
    from airi.discord_bot.context import BotContext
    from airi.domain.spectator import load_policy
    from airi.services.passive_buffer import PassiveBuffer
    from airi.services.spectator_policy import ActivitiesCooldown

    monkeypatch.setattr(client_module.discord, "Client", FakeClient)
    FakeClient.instances.clear()
    channel = FakeChannel()

    state = AppState()
    # Gustos que el matcher debe detectar (el perfil canónico).
    state.world.setdefault("self", {})
    llm_calls = llm

    def build_service(session, state, channel):
        return ConversationService(
            llm=llm_calls,
            state=state,
            gifs=FakeGif(),
            notifier=FakeNotifier(),
            search=FakeSearch(),
            clock=lambda: 1000.0,
        )
    policy = load_policy()
    if enabled:
        policy = type(policy)(
            enabled=True,
            affinity_threshold=policy.affinity_threshold,
            probability_topic=1.0,
            probability_affinity=1.0,
            cooldown_seconds=policy.cooldown_seconds,
            snapshot_max_messages=policy.snapshot_max_messages,
            buffer_max=policy.buffer_max,
            ttl_seconds=policy.ttl_seconds,
        )
    buffer = PassiveBuffer(
        buffer_max=policy.buffer_max,
        ttl_seconds=policy.ttl_seconds,
        clock=lambda: 1000.0,
    )
    gate = ActivitiesCooldown(
        cooldown_seconds=policy.cooldown_seconds, clock=lambda: 1000.0
    )

    def build_ctx(ch):
        policy = load_policy()
        if enabled:
            policy = type(policy)(
                enabled=True,
                affinity_threshold=policy.affinity_threshold,
                probability_topic=1.0,
                probability_affinity=1.0,
                cooldown_seconds=policy.cooldown_seconds,
                snapshot_max_messages=policy.snapshot_max_messages,
                buffer_max=policy.buffer_max,
                ttl_seconds=policy.ttl_seconds,
            )
        ctx = BotContext(
            channel_id=ch.id,
            state=state,
            owner_id=0,
            debounce_seconds=DEBOUNCE,
            request_timeout=5,
            llm_base_url="http://llm.test",
            llm_provider="llama",
            llm_health_check=False,
            persistence=None,
            turn_journal=None,
            build_service=build_service,
            busy_date_owner=lambda exclude_id=None: (None, None),
        )
        ctx.passive_buffer = buffer  # MISMA instancia en cada mensaje
        ctx.spectator_policy = policy
        ctx.spectator_gate = gate  # MISMA instancia en cada mensaje
        return ctx

    client = client_module.create_client(
        build_ctx=build_ctx,
        registry=type("R", (), {"match": lambda self, _c: None})(),
        channel_id=FakeChannel.id,
        manual_shutdown=None,
    )
    client.user = type("U", (), {"id": AIRI_ID, "name": "Airi"})()
    client._channel = channel
    return client, channel, state, buffer, gate


def _send_message(channel, *, mid, content, author_type="user"):
    from airi.testing import FakeUser

    author = FakeUser(99, f"persona[{author_type}]")
    author.bot = False
    message = FakeMessage(author, content, channel, mid=mid)
    channel.on_sent = None
    return message


async def _drive(client, message, channel, *, debug=False):
    if debug:
        logging.basicConfig(level=logging.DEBUG, force=True)
    await client.events["on_message"](message)
    await asyncio.sleep(0.2)


async def _drive_many(client, channel, messages):
    for message in messages:
        await client.events["on_message"](message)
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)


def test_modo_desactivado_responde_como_antes(monkeypatch, service_llm):
    client, channel, state, buffer, gate = _setup(monkeypatch, service_llm, enabled=False)
    msg = _send_message(channel, mid=1, content="palestra común")

    async def scenario():
        await _drive(client, msg, channel)

    asyncio.run(scenario())
    assert len(service_llm.calls) == 1
    # El buffer pasivo NO se llenó (el modo está desactivado).
    assert buffer.snapshot(FakeChannel.id, now=1000.0) == []


def test_modo_activado_sin_senal_guarda_buffer_y_no_llama_llm(monkeypatch, service_llm):
    monkeypatch.setenv("AIRI_SPECTATOR_ENABLED", "1")
    client, channel, state, buffer, gate = _setup(monkeypatch, service_llm, enabled=True)
    msg = _send_message(channel, mid=2, content="cómo está todo")

    async def scenario():
        await _drive(client, msg, channel)

    asyncio.run(scenario())
    assert len(service_llm.calls) == 0
    assert channel.sent == []
    # La escucha persiste: el MISMO buffer guarda el mensaje para el próximo turno.
    snapshot = buffer.snapshot(FakeChannel.id, now=1000.0)
    assert [e.content for e in snapshot] == ["cómo está todo"]


def test_modo_activado_tema_despierta_un_solo_turno(monkeypatch, service_llm):
    monkeypatch.setenv("AIRI_SPECTATOR_ENABLED", "1")
    client, channel, state, buffer, gate = _setup(monkeypatch, service_llm, enabled=True)
    llm = service_llm
    state.world["preferences"] = {
        "loves": ["videojuegos"],
        "dislikes": ["grosero"],
        "favorite_food": "postres y dulces",
        "favorite_flower": "rosas",
    }
    msg_casual = _send_message(channel, mid=4, content="estoy aquí de paseo")
    msg_tema = _send_message(channel, mid=3, content="¿jugamos videojuegos luego?")

    async def scenario():
        await _drive_many(client, channel, [msg_casual, msg_tema])

    asyncio.run(scenario())
    assert len(llm.calls) == 1
    assert channel.sent, "la respuesta espontánea se publicó"
    # Trigger y snapshot se consumen por completo: el tema no queda latente.
    remaining = buffer.snapshot(FakeChannel.id, now=1000.0)
    assert remaining == []


def test_handoff_permite_contestar_a_la_pregunta_de_airi(monkeypatch, service_llm):
    monkeypatch.setenv("AIRI_SPECTATOR_ENABLED", "1")
    monkeypatch.setenv("AIRI_SPECTATOR_HANDOFF_SECONDS", "300")
    client, channel, state, buffer, gate = _setup(monkeypatch, service_llm, enabled=True)
    state.world["preferences"] = {
        "loves": ["videojuegos"],
        "dislikes": [],
        "favorite_food": "dulces",
        "favorite_flower": "tulipanes",
    }
    msg1 = _send_message(channel, mid=20, content="¿videojuegos esta noche?")
    msg2 = _send_message(channel, mid=21, content="sí, me apunto con gusto")
    msg3 = _send_message(channel, mid=22, content="otra cosa cualquiera")

    async def scenario():
        await _drive_many(client, channel, [msg1, msg2, msg3])

    asyncio.run(scenario())
    assert len(service_llm.calls) == 2, "turno espontáneo + respuesta handoff"
    assert not gate.can_fire(FakeChannel.id, "99", now=1000.0)


def test_cooldown_persiste_entre_mensajes(monkeypatch, service_llm):
    monkeypatch.setenv("AIRI_SPECTATOR_ENABLED", "1")
    client, channel, state, buffer, gate = _setup(monkeypatch, service_llm, enabled=True)
    state.world["preferences"] = {
        "loves": ["videojuegos"],
        "dislikes": [],
        "favorite_food": "dulces",
        "favorite_flower": "tulipanes",
    }
    msg1 = _send_message(channel, mid=10, content="¿videojuegos esta noche?")       # tema
    msg2 = _send_message(channel, mid=11, content="vengo del paseo")                 # handoff
    msg3 = _send_message(channel, mid=12, content="nada más, gracias por el ánimo")  # ya sin handoff
    msg4 = _send_message(channel, mid=13, content="otra vez ¿videojuegos?")          # cooldown

    async def scenario():
        await _drive_many(client, channel, [msg1, msg2, msg3, msg4])

    asyncio.run(scenario())
    assert len(service_llm.calls) == 2, "tema inicial + handoff; cooldown bloquea msg4"
    # La instancia del gate persiste: sigue armada al cierre del escenario.
    assert not gate.can_fire(FakeChannel.id, "99", now=1000.0)
