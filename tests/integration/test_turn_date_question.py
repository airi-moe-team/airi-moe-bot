"""Integración de la capa Discord: publicación y respuesta de la pregunta.

Se comprueba que, cuando la cita alcanza el evento `question`, el bot publica
el embed con sus botones (y solo eso), y que al pulsar uno se resuelve el
dado, se aplica el swing y se lanza el turno de reacción de Airi.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from airi.discord_bot import turn as discord_turn
from airi.discord_bot.views import date as date_views
from airi.domain.dates import new_date_session
from airi.testing import FakeUser, make_state

ANA = FakeUser(1, "Ana")
# La capa de Discord trabaja con el reloj real (las citas caducan por tiempo).
NOW = time.time()

QUESTION = {
    "text": "¿Qué es lo que más te gusta de mí?",
    "options": [
        {
            "label": "Tu risa",
            "action": "le digo que su risa",
            "up_chance": 1.0,
            "delta_up": 20,
            "delta_down": -8,
        },
        {
            "label": "Tu compañía",
            "action": "le digo que su compañía",
            "up_chance": 0.5,
            "delta_up": 12,
            "delta_down": -6,
        },
    ],
}


def run(coro):
    return asyncio.run(coro)


class _FakeChannel:
    def __init__(self):
        self.id = 99
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class _FakeInteraction:
    def __init__(self, user):
        self.user = user
        self.channel = _FakeChannel()
        self.followup = SimpleNamespace(send=self._send)

    async def _send(self, content=None, **kwargs):
        self.followup_messages = getattr(self, "followup_messages", [])
        self.followup_messages.append(content)


def _ctx(state, *, question=None, resolve=None):
    session = state.dates.get("1")
    if isinstance(session, dict) and question is not None:
        session["question"] = question
        session["question_used"] = True
        session["question_pending"] = True
    calls = {"expired": [], "applied": []}

    def expire_question(uid, **kw):
        calls["expired"].append(uid)
        if isinstance(session, dict):
            session["question_pending"] = False
        return True

    def resolve_question(session, index):
        if resolve is not None:
            return resolve
        return {
            "index": index, "win": True, "delta": 20,
            "label": "Tu risa", "action": "le digo que su risa",
        }

    def apply_question_result(session, result, *, user_id=None, now=None):
        calls["applied"].append(result)
        session["question_pending"] = False
        return session

    ctx = SimpleNamespace(
        state=state,
        expire_question=expire_question,
        resolve_question=resolve_question,
        apply_question_result=apply_question_result,
        handle_question_answer=lambda *args: None,
        expire_stale_dates=lambda now=None: [],
        calls=calls,
    )
    return ctx


def _state_with_date():
    state, _ = make_state(users={"1": {"name": "Ana"}})
    state.dates["1"] = new_date_session("paseo", 40, now=NOW)
    return state


def test_send_question_publishes_the_embed_with_its_buttons():
    state = _state_with_date()
    ctx = _ctx(state, question=QUESTION)
    channel = _FakeChannel()

    run(discord_turn._send_question(ctx, channel, "1", state.dates["1"], now=NOW))

    assert len(channel.sent) == 1
    content, kwargs = channel.sent[0]
    assert content is None
    embed = kwargs["embed"]
    assert embed.title == "💞 Airi te pregunta algo importante"
    assert embed.description == QUESTION["text"]
    view = kwargs["view"]
    assert isinstance(view, date_views.DateQuestionView)
    assert len(view.children) == 2


def test_send_question_expires_it_when_there_is_no_time_left():
    state = _state_with_date()
    session = state.dates["1"]
    session["started_at"] = NOW - 10_000  # la cita está a punto de expirar
    ctx = _ctx(state, question=QUESTION)
    channel = _FakeChannel()

    run(discord_turn._send_question(ctx, channel, "1", session, now=NOW))

    # La pregunta se cancela y se avisa: no quedan botones colgando.
    assert ctx.calls["expired"] == ["1"]
    assert session["question_pending"] is False
    assert channel.sent and channel.sent[0][0]


def test_handle_question_answer_resolves_and_reacts(monkeypatch):
    state = _state_with_date()
    ctx = _ctx(state, question=QUESTION)
    interaction = _FakeInteraction(ANA)
    calls = {}

    async def _fake_run_user_turn(ctx_, channel, author, merged, **kwargs):
        calls["kind"] = kwargs.get("kind")
        calls["note"] = kwargs.get("extra_note")
        calls["suppress"] = kwargs.get("suppress_affinity")
        calls["text"] = merged[0][1]

    monkeypatch.setattr(discord_turn, "run_user_turn", _fake_run_user_turn)

    run(discord_turn.handle_question_answer(ctx, interaction, 0))

    assert ctx.calls["applied"], "el swing debe aplicarse"
    assert calls["kind"] == "date_question_result"
    assert calls["suppress"] is True
    assert "pregunta" in calls["note"].lower()


def test_handle_question_answer_ignores_a_closed_date():
    state = _state_with_date()
    state.dates["1"]["state"] = "closed"
    ctx = _ctx(state, question=QUESTION)
    interaction = _FakeInteraction(ANA)

    run(discord_turn.handle_question_answer(ctx, interaction, 0))

    assert ctx.calls["applied"] == []
