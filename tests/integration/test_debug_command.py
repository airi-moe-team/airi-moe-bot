"""Tests del comando !debug (solo dueño) con dobles de Discord."""

import asyncio

from airi.discord_bot.commands import debug
from airi.discord_bot.context import BotContext
from airi.observability.trace import TurnTrace
from airi.services.state import AppState


class FakeAuthor:
    def __init__(self, user_id, bot=False):
        self.id = user_id
        self.bot = bot
        self.display_name = f"User{user_id}"


class FakeChannel:
    def __init__(self, channel_id=7):
        self.id = channel_id
        self.sent = []
        self.files = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)
        if "file" in kwargs:
            self.files.append(kwargs["file"])
        if "embed" in kwargs:
            self.files.append(("embed", kwargs["embed"]))


class FakeMessage:
    def __init__(self, content, author, channel):
        self.content = content
        self.author = author
        self.channel = channel
        self.replies = []

    async def reply(self, content=None, **kwargs):
        self.replies.append(content)


def make_ctx(owner_id=1):
    return BotContext(channel_id=7, state=AppState(), owner_id=owner_id)


def run(coro):
    return asyncio.run(coro)


def test_debug_rejects_non_owner():
    ctx = make_ctx(owner_id=1)
    channel = FakeChannel()
    msg = FakeMessage("!debug turno", FakeAuthor(2), channel)

    run(debug.handle(ctx, msg))

    assert msg.replies == ["Solo el dueño del canal puede usar `!debug`."]
    assert channel.sent == []


def test_debug_usage_on_bad_args():
    ctx = make_ctx()
    channel = FakeChannel()
    msg = FakeMessage("!debug", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert len(msg.replies) == 1
    assert "!debug turno" in msg.replies[0]


def test_debug_turno_without_trace():
    ctx = make_ctx()
    channel = FakeChannel()
    msg = FakeMessage("!debug turno", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert "No hay ningún turno registrado" in msg.replies[0]


def _remember(ctx):
    trace = TurnTrace(
        correlation_id="ab12",
        user_id="1",
        user_name="User1",
        channel_id="7",
        final_reply="¡Hola!",
        affinity_before=10,
        affinity_after=12,
        affinity_applied=2,
        level_before="Conocida",
        level_after="Conocida",
        gif="happy",
        grounded=True,
        llm_ms=120,
    )
    ctx.remember_trace(trace)
    return trace


def test_debug_turno_shows_summary_embed():
    ctx = make_ctx()
    channel = FakeChannel()
    _remember(ctx)
    msg = FakeMessage("!debug turno", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert msg.replies == []
    assert len(channel.sent) == 1  # el texto es None; va en embed
    _kind, embed = channel.files[0]
    assert _kind == "embed"
    assert "ab12" in embed.description
    assert "10 → 12" in embed.description
    # Sin cita activa no se muestra "continue" como si fuera una decisión.
    assert "decisión cita: — (sin cita)" in embed.description


def test_debug_turno_shows_date_decision_only_during_date():
    ctx = make_ctx()
    channel = FakeChannel()
    trace = TurnTrace(
        correlation_id="date01",
        user_id="1",
        channel_id="7",
        final_reply="qué bien",
        in_date=True,
        date_decision="crisis",
    )
    ctx.remember_trace(trace)
    msg = FakeMessage("!debug turno", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    _kind, embed = channel.files[0]
    assert "decisión cita: crisis" in embed.description


def test_debug_trace_sends_json_file(tmp_path):
    ctx = make_ctx()
    channel = FakeChannel()
    trace = _remember(ctx)
    msg = FakeMessage("!debug trace", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert len(channel.files) == 1
    file = channel.files[0]
    assert file.filename == "trace-ab12.json"
    file.fp.seek(0)
    import json

    payload = json.loads(file.fp.read().decode("utf-8"))
    assert payload["correlation_id"] == "ab12"
    assert payload["final_reply"] == trace.final_reply
    assert channel.sent and "ab12" in channel.sent[0]


def test_last_trace_is_per_user():
    ctx = make_ctx()
    ctx.remember_trace(TurnTrace(correlation_id="a", user_id="1", channel_id="7"))
    ctx.remember_trace(TurnTrace(correlation_id="b", user_id="2", channel_id="7"))

    assert ctx.last_trace_for(7, 1).correlation_id == "a"
    assert ctx.last_trace_for(7, 2).correlation_id == "b"
    assert ctx.last_trace_for(7, 9) is None


def test_last_trace_uses_latest_started_at_not_insertion_order():
    ctx = make_ctx()
    # El turno más nuevo se inserta primero y el más antiguo termina después.
    ctx.remember_trace(
        TurnTrace(
            correlation_id="nuevo",
            user_id="1",
            channel_id="7",
            started_at=200.0,
        )
    )
    ctx.remember_trace(
        TurnTrace(
            correlation_id="antiguo",
            user_id="1",
            channel_id="7",
            started_at=100.0,
        )
    )

    assert ctx.last_trace_for(7, 1).correlation_id == "nuevo"


def test_last_trace_ties_prefer_most_recently_inserted():
    ctx = make_ctx()
    ctx.remember_trace(
        TurnTrace(
            correlation_id="primero",
            user_id="1",
            channel_id="7",
            started_at=100.0,
        )
    )
    ctx.remember_trace(
        TurnTrace(
            correlation_id="segundo",
            user_id="1",
            channel_id="7",
            started_at=100.0,
        )
    )

    assert ctx.last_trace_for(7, 1).correlation_id == "segundo"


# ============================================================
# Subcomandos nuevos: ultimo / id / errores / clear
# ============================================================


def _save(ctx, **kwargs):
    """Guarda un evento en el TraceStore del contexto y lo devuelve."""
    ev = TurnTrace(**kwargs)
    run(ctx.state.traces.save(ev))
    return ev


def test_debug_ultimo_lists_recent_events():
    ctx = make_ctx()
    channel = FakeChannel()
    _save(ctx, correlation_id="e1", kind="message", user_id="1",
          user_name="User1", channel_id="7", final_reply="hola")
    _save(ctx, correlation_id="e2", kind="gift", user_id="2",
          user_name="User2", channel_id="7", final_reply="gracias")
    msg = FakeMessage("!debug ultimo 2", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert msg.replies == []
    _kind, embed = channel.files[0]
    assert "e1" in embed.description
    assert "e2" in embed.description


def test_debug_ultimo_defaults_to_one():
    ctx = make_ctx()
    channel = FakeChannel()
    _save(ctx, correlation_id="only", kind="message", user_id="1", channel_id="7")
    msg = FakeMessage("!debug ultimo", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    _kind, embed = channel.files[0]
    assert "only" in embed.description


def test_debug_ultimo_empty_replies():
    ctx = make_ctx()
    channel = FakeChannel()
    msg = FakeMessage("!debug ultimo", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert "No hay eventos" in msg.replies[0]


def test_debug_ultimo_bad_n_shows_usage():
    ctx = make_ctx()
    channel = FakeChannel()
    msg = FakeMessage("!debug ultimo abc", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert msg.replies and "!debug ultimo" in msg.replies[0]


def test_debug_id_sends_json_file():
    ctx = make_ctx()
    channel = FakeChannel()
    _save(ctx, correlation_id="abc123", kind="gift", user_id="1",
          channel_id="7", final_reply="x")
    msg = FakeMessage("!debug id abc123", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert len(channel.files) == 1
    file = channel.files[0]
    assert file.filename == "trace-abc123.json"
    file.fp.seek(0)
    import json

    payload = json.loads(file.fp.read().decode("utf-8"))
    assert payload["correlation_id"] == "abc123"
    assert payload["kind"] == "gift"


def test_debug_id_not_found():
    ctx = make_ctx()
    channel = FakeChannel()
    msg = FakeMessage("!debug id nope", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert "No encontré" in msg.replies[0]


def test_debug_id_missing_cid_shows_usage():
    ctx = make_ctx()
    channel = FakeChannel()
    msg = FakeMessage("!debug id", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert msg.replies and "!debug id" in msg.replies[0]


def test_debug_errores_lists_only_events_with_errors():
    ctx = make_ctx()
    channel = FakeChannel()
    _save(ctx, correlation_id="ok", kind="message", user_id="1", channel_id="7")
    _save(ctx, correlation_id="bad", kind="command", user_id="1",
          channel_id="7", errors=[{"type": "X", "msg": "boom"}])
    msg = FakeMessage("!debug errores", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    _kind, embed = channel.files[0]
    assert "bad" in embed.description
    assert "ok" not in embed.description


def test_debug_errores_without_errors():
    ctx = make_ctx()
    channel = FakeChannel()
    _save(ctx, correlation_id="ok", kind="message", user_id="1", channel_id="7")
    msg = FakeMessage("!debug errores", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert "No hay errores" in msg.replies[0]


def test_debug_clear_empties_ring():
    ctx = make_ctx()
    channel = FakeChannel()
    _save(ctx, correlation_id="a", kind="message", user_id="1", channel_id="7")
    _save(ctx, correlation_id="b", kind="message", user_id="1", channel_id="7")
    msg = FakeMessage("!debug clear", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert "vaciado" in msg.replies[0]
    assert len(ctx.state.traces) == 0


def test_debug_estado_shows_storage_info_without_private_data():
    ctx = make_ctx()
    ctx.storage_info = {
        "path": "data/state.json",
        "schema_version": 1,
        "state_version": 4,
        "recovered": False,
        "migration": "migrated",
        "pending_publications": 2,
        "quarantine_path": "",
    }
    channel = FakeChannel()
    msg = FakeMessage("!debug estado", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    _kind, embed = channel.files[0]
    assert "state.json" in embed.description
    assert "state_version: 4" in embed.description
    assert "migrated" in embed.description
    assert "pendientes: 2" in embed.description
    assert "recuerdo" not in embed.description


def test_debug_estado_without_storage_info_replies_safely():
    ctx = make_ctx()
    channel = FakeChannel()
    msg = FakeMessage("!debug estado", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert "diagnóstico" in msg.replies[0].lower()


def test_debug_unknown_subcommand_shows_usage():
    ctx = make_ctx()
    channel = FakeChannel()
    msg = FakeMessage("!debug banana", FakeAuthor(1), channel)

    run(debug.handle(ctx, msg))

    assert msg.replies and "Uso" in msg.replies[0]

