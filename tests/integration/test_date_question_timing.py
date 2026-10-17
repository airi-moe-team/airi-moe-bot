"""1.3 / D4: la pregunta decisiva solo se lanza si hay tiempo para responderla.

Sin tiempo: no se publica el embed, se cancela `question_pending` y se avisa.
Con pregunta forzada: se alarga la cita lo justo para que sea respondible.
"""

import asyncio
from types import SimpleNamespace

from airi.discord_bot import turn as discord_turn
from airi.discord_bot.client import build_date_glue
from airi.domain.constants import DATE_MAX_SECONDS, DATE_QUESTION_MIN_SECONDS
from airi.domain.dates import date_seconds_left, new_date_session
from airi.domain.texts import DATE_QUESTION_FALLBACK, DATE_QUESTION_MISSED_TEXT
from airi.testing import make_state

NOW = 1_000_000.0


class _FakeChannel:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, **kwargs):
        self.messages.append({"content": content, **kwargs})
        return None


def _ctx(state, glue):
    return SimpleNamespace(
        state=state,
        expire_question=glue.expire_question,
        handle_question_answer=lambda *args, **kwargs: None,
    )


def _session_with_question(state, *, remaining, forced):
    started = NOW - (DATE_MAX_SECONDS - remaining)
    session = new_date_session("paseo", 40, now=started)
    session["question"] = {
        "text": DATE_QUESTION_FALLBACK["text"],
        "options": list(DATE_QUESTION_FALLBACK["options"]),
    }
    session["question_used"] = True
    session["question_pending"] = True
    session["question_forced"] = forced
    session["question_asked_at"] = NOW
    state.dates["1"] = session
    return session


def _glue(state):
    return build_date_glue(state, llm_url="http://x", request_timeout=5)


def test_no_question_when_too_little_time_left():
    state, _ = make_state()
    session = _session_with_question(state, remaining=25, forced=False)
    channel = _FakeChannel()

    asyncio.run(
        discord_turn._send_question(
            _ctx(state, _glue(state)), channel, "1", session, now=NOW
        )
    )

    assert session["question_pending"] is False
    assert channel.messages
    last = channel.messages[-1]
    # La alerta de momento perdido es un mensaje del sistema: va en embed.
    assert last["content"] is None
    assert last["embed"].description == DATE_QUESTION_MISSED_TEXT


def test_question_sent_normally_with_enough_time():
    state, _ = make_state()
    session = _session_with_question(state, remaining=200, forced=False)
    channel = _FakeChannel()

    asyncio.run(
        discord_turn._send_question(
            _ctx(state, _glue(state)), channel, "1", session, now=NOW
        )
    )

    assert session["question_pending"] is True
    assert channel.messages[-1]["embed"] is not None
    assert channel.messages[-1]["view"] is not None


def test_forced_question_extends_the_date():
    state, _ = make_state()
    session = _session_with_question(state, remaining=25, forced=True)
    started_before = session["started_at"]
    channel = _FakeChannel()

    asyncio.run(
        discord_turn._send_question(
            _ctx(state, _glue(state)), channel, "1", session, now=NOW
        )
    )

    assert session["started_at"] > started_before
    assert date_seconds_left(session, NOW) >= DATE_QUESTION_MIN_SECONDS
    assert channel.messages[-1]["embed"] is not None
    assert channel.messages[-1]["view"] is not None


def test_short_question_timeout_is_at_least_the_minimum():
    state, _ = make_state()
    session = _session_with_question(state, remaining=70, forced=False)
    channel = _FakeChannel()

    asyncio.run(
        discord_turn._send_question(
            _ctx(state, _glue(state)), channel, "1", session, now=NOW
        )
    )

    view = channel.messages[-1]["view"]
    assert view.timeout >= DATE_QUESTION_MIN_SECONDS
