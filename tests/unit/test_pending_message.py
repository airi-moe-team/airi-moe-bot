"""Pruebas unitarias del tracker de mensajes pendientes."""

from __future__ import annotations

import pytest

from airi.services.pending_message import PendingMessageTracker


class FakeMessage:
    def __init__(self, message_id, author_id, content, channel_id, created_at):
        self.id = message_id
        self.author = type(
            "Author", (), {"id": author_id, "bot": False}
        )()
        self.content = content
        self.channel_id = channel_id
        self.created_at = created_at


def bot_message(message_id, content, created_at, *, bot_id=999, channel_id=1):
    message = FakeMessage(message_id, bot_id, content, channel_id, created_at)
    message.author = type("Author", (), {"id": bot_id, "bot": True})()
    return message


def test_find_pending_message_primero_no_respondido():
    tracker = PendingMessageTracker()
    msgs = [
        FakeMessage("2", 101, "como estas", 1, 900.0),
        FakeMessage("1", 100, "hola", 1, 1000.0),
    ]
    pending = tracker.find_pending_message(msgs, bot_id=999, max_age=86400, now=2000.0)
    assert pending is not None
    assert pending.id == "2"


def test_find_pending_message_excluye_cmds():
    tracker = PendingMessageTracker()
    msgs = [
        FakeMessage("1", 100, "!comando", 1, 1000.0),
        FakeMessage("2", 101, "hola", 1, 900.0),
    ]
    pending = tracker.find_pending_message(msgs, bot_id=999, max_age=86400, now=2000.0)
    assert pending is not None
    assert pending.id == "2"


def test_find_pending_message_excluye_bot():
    tracker = PendingMessageTracker()
    # Mas reciente: mensaje de bot. Segundo: mensaje humano.
    msgs = [
        FakeMessage("2", 101, "como estas", 1, 900.0),  # humano
        FakeMessage("1", 100, "hola", 1, 1000.0),  # bot
    ]
    msgs[1].author = type("Author", (), {"id": 100, "bot": True})()
    pending = tracker.find_pending_message(msgs, bot_id=999, max_age=86400, now=2000.0)
    # Debe filtrar el mensaje de bot; devolver el human.
    assert pending is not None
    assert pending.id == "2"


def test_mark_answered_y_is_answered():
    tracker = PendingMessageTracker()
    tracker.mark_answered(1, "100")
    assert tracker.is_answered(1, "100") is True
    assert tracker.is_answered(1, "200") is False


def test_find_pending_message_excluye_respondidos():
    tracker = PendingMessageTracker()
    tracker.mark_answered(1, "2")
    msgs = [
        FakeMessage("1", 100, "hola", 1, 1000.0),
        FakeMessage("2", 101, "como estas", 1, 900.0),
    ]
    pending = tracker.find_pending_message(msgs, bot_id=999, max_age=86400, now=2000.0)
    assert pending is not None
    assert pending.id == "1"


def test_persistence_en_dict():
    tracker = PendingMessageTracker()
    tracker.mark_answered(1, "100")
    tracker.mark_answered(1, "200")
    tracker.mark_answered(2, "300")
    data = tracker.to_dict()
    assert data["answered_message_ids"]["1"] == ["100", "200"]
    assert data["answered_message_ids"]["2"] == ["300"]

    # Cargar de vuelta
    loaded = PendingMessageTracker.from_dict(data)
    assert loaded.is_answered(1, "100") is True
    assert loaded.is_answered(1, "300") is False  # canal 1, no chan 2


# ---------------------------------------------------------------------------
# Cortafuegos temporal: Airi ya respondió -> nada anterior sigue pendiente
# ---------------------------------------------------------------------------


def test_no_revive_mensaje_anterior_a_la_ultima_respuesta_de_airi():
    """Caso real: 'que hacen' respondido en contexto no debe revivir."""
    tracker = PendingMessageTracker()
    msgs = [
        bot_message("30", "Justo charlando con ustedes, gustavodx", 1100.0),
        FakeMessage("20", 101, "que hacen", 1, 1000.0),
        FakeMessage("10", 101, "yahoo", 1, 900.0),
    ]
    pending = tracker.find_pending_message(msgs, bot_id=999, max_age=86400, now=2000.0)
    assert pending is None


def test_embed_de_sistema_no_corta_la_busqueda():
    """El embed de conexión/GIF no es una respuesta conversacional."""
    tracker = PendingMessageTracker()
    msgs = [
        bot_message("30", "", 1100.0),
        FakeMessage("20", 101, "hola", 1, 1000.0),
    ]
    pending = tracker.find_pending_message(msgs, bot_id=999, max_age=86400, now=2000.0)
    assert pending is not None
    assert pending.id == "20"


def test_si_el_mensaje_es_posterior_a_la_ultima_respuesta_sigue_pendiente():
    tracker = PendingMessageTracker()
    msgs = [
        FakeMessage("40", 101, "sigues ahí", 1, 1200.0),
        bot_message("30", "hola", 1100.0),
        FakeMessage("20", 101, "que hacen", 1, 1000.0),
    ]
    pending = tracker.find_pending_message(msgs, bot_id=999, max_age=86400, now=2000.0)
    assert pending is not None
    assert pending.id == "40"


def test_mark_answered_many_persiste_todos_en_una_sola_escritura():
    from types import SimpleNamespace

    saved = []
    state = SimpleNamespace(world={}, save_world=lambda: saved.append(1))
    tracker = PendingMessageTracker(state=state)

    tracker.mark_answered_many(1, ["10", "11", "10", None])

    assert tracker.is_answered(1, "10") is True
    assert tracker.is_answered(1, "11") is True
    assert state.world["answered_message_ids"]["1"] == ["10", "11"]
    assert len(saved) == 1


# ---------------------------------------------------------------------------
# El turno marca todo lo que cubrió (snapshot + triggers + reply_target)
# ---------------------------------------------------------------------------


def test_turn_consumed_ids_incluye_snapshot_y_triggers():
    from airi.discord_bot.turn import _turn_consumed_ids

    ids = _turn_consumed_ids(
        ["1"],
        ["2"],
        [
            {"message_id": "3"},
            {"message_id": ""},
            "no-es-dict",
            {"sin_id": "x"},
        ],
    )

    assert ids == {"1", "2", "3"}


def test_mark_turn_answered_incluye_reply_target_y_consumidos():
    from types import SimpleNamespace

    from airi.discord_bot.turn import _mark_turn_answered

    class _Tracker:
        def __init__(self):
            self.calls = []

        def mark_answered_many(self, channel_id, message_ids):
            self.calls.append((channel_id, set(message_ids)))

    tracker = _Tracker()
    ctx = SimpleNamespace(pending_message_tracker=tracker)

    _mark_turn_answered(
        ctx,
        SimpleNamespace(id=7),
        SimpleNamespace(id="99"),
        {"1", "2"},
    )

    assert tracker.calls == [(7, {"1", "2", "99"})]
