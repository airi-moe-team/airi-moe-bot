"""Avisos de estado del bot (conectado/desconectado) y respuesta pendiente.

Al arrancar, Airi anuncia en cada canal autorizado que ha vuelto y, si el
último mensaje del canal es de un humano (nadie más contestó), le responde.
Al apagar, anuncia que se va.
"""

import asyncio
import datetime
from types import SimpleNamespace

import discord

from airi.discord_bot import turn as turn_module
from airi.discord_bot.client import create_client, pending_user_message

BOT_ID = 999
NOW = datetime.datetime.now(datetime.timezone.utc)


class FakeAuthor:
    def __init__(self, user_id, bot=False):
        self.id = user_id
        self.bot = bot
        self.display_name = f"User{user_id}"


class FakeMessage:
    def __init__(self, content, author, channel=None, created_at=NOW):
        self.content = content
        self.author = author
        self.channel = channel
        self.created_at = created_at


class FakeChannel:
    """Canal de Discord simulado con historial y registro de envíos."""

    def __init__(self, channel_id, history=None):
        self.id = channel_id
        self.sent = []  # lista de embeds (kwargs['embed'])
        self._history = list(history or [])

    async def send(self, content=None, **kwargs):
        self.sent.append(kwargs.get("embed", content))

    async def history(self, *, limit=1):
        # El fake del otro test es un método async. Pero en discord.py real
        # `channel.history` es un async iterator. Para simplificar ambos casos,
        # devuelvo el iterador async directamente cuando se llama.
        async def _gen():
            for msg in self._history[:limit]:
                yield msg
        return _gen()

    def titles(self):
        return [getattr(e, "title", None) for e in self.sent]


def run(coro):
    return asyncio.run(coro)


def make_client(monkeypatch, allowed_ids, **kwargs):
    """Cliente con canales falsos resolubles y turnos registrados."""
    channels = {}
    turn_calls = []

    async def fake_run_user_turn(ctx, channel, author, merged, reply_target=None):
        turn_calls.append(
            {
                "channel": channel,
                "author": author,
                "merged": merged,
                "reply_target": reply_target,
            }
        )

    monkeypatch.setattr(turn_module, "run_user_turn", fake_run_user_turn)

    async def fetch_channel(cid):
        return channels[cid]

    def make_ctx(channel):
        return SimpleNamespace(channel_id=channel.id, state=SimpleNamespace(dates={}))

    client = create_client(
        build_ctx=make_ctx,
        registry=SimpleNamespace(match=lambda content: None),
        channel_ids=allowed_ids,
        **kwargs,
    )
    # discord.py 2.7.1 no permite asignar `client.user`; para simular, ponemos
    # el user en `client._connection` si existe, o lo dejamos para que `on_ready`
    # lea de ahí.
    try:
        client._connection.user = FakeAuthor(BOT_ID, bot=True)
    except Exception:
        pass
    if getattr(client, "user", None) is None:
        client._user = FakeAuthor(BOT_ID, bot=True)  # fallback para getattr
        try:
            type(client).user = property(lambda self: getattr(self, "_user", None))
        except Exception:
            pass
    monkeypatch.setattr(client, "fetch_channel", fetch_channel)
    for cid in allowed_ids:
        channels[cid] = FakeChannel(cid)
    return client, channels, turn_calls


# ---------------------------------------------------------------------------
# pending_user_message (helper puro)
# ---------------------------------------------------------------------------


def test_pending_returns_the_last_message_when_it_is_from_a_human():
    msg = FakeMessage("hola Airi", FakeAuthor(1))

    assert pending_user_message([msg], BOT_ID, now=NOW) is msg


def test_pending_ignores_empty_history():
    assert pending_user_message([], BOT_ID) is None


def test_pending_ignores_when_airi_spoke_last():
    history = [FakeMessage("…", FakeAuthor(BOT_ID, bot=True)), FakeMessage("hola", FakeAuthor(1))]

    assert pending_user_message(history, BOT_ID) is None


def test_pending_ignores_when_the_last_message_is_a_command():
    assert pending_user_message([FakeMessage("!ranking", FakeAuthor(1))], BOT_ID) is None


def test_pending_ignores_blank_messages():
    assert pending_user_message([FakeMessage("   ", FakeAuthor(1))], BOT_ID) is None


def test_pending_ignores_messages_older_than_max_age():
    old = FakeMessage("hola", FakeAuthor(1), created_at=NOW - datetime.timedelta(hours=2))

    assert pending_user_message([old], BOT_ID, now=NOW, max_age=3600) is None


def test_pending_accepts_messages_inside_max_age():
    recent = FakeMessage("hola", FakeAuthor(1), created_at=NOW - datetime.timedelta(minutes=30))

    assert pending_user_message([recent], BOT_ID, now=NOW, max_age=3600) is recent


def test_pending_max_age_none_disables_the_age_check():
    old = FakeMessage("hola", FakeAuthor(1), created_at=datetime.datetime(2025, 1, 1, 11, 0, tzinfo=datetime.timezone.utc))

    assert pending_user_message([old], BOT_ID, now=NOW, max_age=None) is old


# ---------------------------------------------------------------------------
# on_ready
# ---------------------------------------------------------------------------


def test_on_ready_greeting(monkeypatch):
    client, channels, _ = make_client(monkeypatch, {111, 222})
    for channel in channels.values():
        channel._history.append(FakeMessage("…", FakeAuthor(BOT_ID, bot=True)))

    run(client.on_ready())

    assert channels[111].titles() == ["🟢 Airi se ha conectado"]
    assert channels[222].titles() == ["🟢 Airi se ha conectado"]


def test_on_ready_replies_to_the_pending_message(monkeypatch):
    pending = FakeMessage("¿sigues ahí?", FakeAuthor(42))
    client, channels, turn_calls = make_client(monkeypatch, {111})
    channels[111]._history.append(pending)

    run(client.on_ready())

    assert len(turn_calls) == 1
    call = turn_calls[0]
    assert call["author"].id == 42
    assert call["merged"] == [(pending.author, "¿sigues ahí?")]
    assert call["reply_target"] is pending
    # El saludo se publica ANTES de la respuesta pendiente.
    assert channels[111].titles() == ["🟢 Airi se ha conectado"]


def test_on_ready_ignores_pending_command(monkeypatch):
    client, channels, turn_calls = make_client(monkeypatch, {111})
    channels[111]._history.append(FakeMessage("!ranking", FakeAuthor(42)))

    run(client.on_ready())

    assert turn_calls == []
    assert channels[111].titles() == ["🟢 Airi se ha conectado"]


def test_on_ready_does_not_reply_to_an_answered_conversation(monkeypatch):
    client, channels, turn_calls = make_client(monkeypatch, {111})
    channels[111]._history.append(FakeMessage("…", FakeAuthor(BOT_ID, bot=True)))
    channels[111]._history.append(FakeMessage("hola", FakeAuthor(42)))

    run(client.on_ready())

    assert turn_calls == []


def test_on_ready_announces_only_once_on_reconnect(monkeypatch):
    client, channels, turn_calls = make_client(monkeypatch, {111})
    for channel in channels.values():
        channel._history.append(FakeMessage("…", FakeAuthor(BOT_ID, bot=True)))

    run(client.on_ready())
    run(client.on_ready())

    assert channels[111].titles() == ["🟢 Airi se ha conectado"]


def test_on_ready_disabled_when_notices_and_catchup_are_off(monkeypatch):
    client, channels, turn_calls = make_client(
        monkeypatch, {111}, online_notice=False, answer_pending_on_start=False
    )
    channels[111]._history.append(FakeMessage("hola", FakeAuthor(42)))

    run(client.on_ready())

    assert channels[111].sent == []
    assert turn_calls == []


def test_on_ready_notice_disabled_still_replies_to_pending(monkeypatch):
    pending = FakeMessage("hola", FakeAuthor(42))
    client, channels, turn_calls = make_client(
        monkeypatch, {111}, online_notice=False, answer_pending_on_start=True
    )
    channels[111]._history.append(pending)

    run(client.on_ready())

    assert channels[111].sent == []
    assert len(turn_calls) == 1


def test_on_ready_keeps_going_when_a_channel_cannot_be_fetched(monkeypatch):
    client, channels, turn_calls = make_client(monkeypatch, {111, 222})

    async def flaky(cid):
        if cid == 111:
            raise RuntimeError("sin acceso")
        return channels[cid]

    monkeypatch.setattr(client, "fetch_channel", flaky)
    for channel in channels.values():
        channel._history.append(FakeMessage("…", FakeAuthor(BOT_ID, bot=True)))

    run(client.on_ready())

    assert channels[111].sent == []
    assert channels[222].titles() == ["🟢 Airi se ha conectado"]


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def test_close_announces_the_disconnect_and_closes_once(monkeypatch):
    closed = []

    async def fake_close(self):
        closed.append(True)

    monkeypatch.setattr(discord.Client, "close", fake_close)

    client, channels, _turn_calls = make_client(monkeypatch, {111})
    for channel in channels.values():
        channel._history.append(FakeMessage("…", FakeAuthor(BOT_ID, bot=True)))
    run(client.on_ready())
    channels[111]._history.append(FakeMessage("…", FakeAuthor(BOT_ID, bot=True)))

    run(client.close())
    run(client.close())

    assert channels[111].titles() == ["🟢 Airi se ha conectado", "🔴 Airi se ha desconectado"]
    assert closed == [True, True]


def test_close_says_goodbye_even_when_the_channel_was_never_resolved(monkeypatch):
    closed = []

    async def fake_close(self):
        closed.append(True)

    monkeypatch.setattr(discord.Client, "close", fake_close)

    client, channels, _turn_calls = make_client(monkeypatch, {111})
    channels[111]._history.append(FakeMessage("…", FakeAuthor(BOT_ID, bot=True)))

    async def no_channel(cid):
        raise RuntimeError("sin acceso")

    monkeypatch.setattr(client, "fetch_channel", no_channel)
    run(client.on_ready())

    run(client.close())

    assert channels[111].sent == []


def test_close_farewell_can_be_disabled(monkeypatch):
    closed = []

    async def fake_close(self):
        closed.append(True)

    monkeypatch.setattr(discord.Client, "close", fake_close)

    client, channels, _turn_calls = make_client(monkeypatch, {111}, online_notice=False)
    for channel in channels.values():
        channel._history.append(FakeMessage("…", FakeAuthor(BOT_ID, bot=True)))
    run(client.on_ready())

    run(client.close())

    assert channels[111].sent == []
    assert closed == [True]
