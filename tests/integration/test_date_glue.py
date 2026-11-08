"""Tests de los pegamentos Discord↔dominio construidos por `build_date_glue`.

La migración hexagonal dejó estos métodos como stubs vacíos dentro de
`run_bot`, lo que rompía `!cita` (firma incorrecta) y `!regalo`. Aquí se
verifica el comportamiento de `build_date_glue` con un `AppState` en memoria
y una `session` HTTP falsa (sin red ni Discord).
"""

import asyncio
import json
import os
import time

from airi.discord_bot.client import build_date_glue
from airi.domain.constants import DATE_MAX_SECONDS, DATE_SCENE_MAX_TOKENS, DATE_SCENES
from airi.domain.dates import new_date_session
from airi.testing import FakeUser, make_state

ANA = FakeUser(1, "Ana")
BEA = FakeUser(2, "Bea")
NOW = 1_000_000.0
# `busy_date_owner`/`notify_busy` expiran con reloj real (`time.time()`), así que
# las sesiones que deben seguir vivas usan una marca temporal realista.
REAL_NOW = time.time()


def run(coro):
    return asyncio.run(coro)


# --- Dobles HTTP -----------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeSession:
    """Sustituto mínimo de ``aiohttp.ClientSession`` para `HttpLlmClient.post`."""

    def __init__(self, content=None, *, exc=None):
        self._content = content
        self._exc = exc
        self.payloads = []

    def post(self, url, json=None, timeout=None):  # noqa: A002 - firma aiohttp
        self.payloads.append(json)
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(
            {"choices": [{"message": {"content": self._content}}]}
        )


class _FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)


def _glue(state):
    return build_date_glue(
        state, llm_base_url="http://x", request_timeout=5
    )


# --- propose_scenes --------------------------------------------------------


def test_propose_scenes_parses_model_scenes():
    state, _ = make_state()
    glue = _glue(state)
    content = json.dumps({"scenes": ["un paseo", "un café", "el cine"]})

    scenes = run(glue.propose_scenes(_FakeSession(content), ANA))

    assert scenes == ["un paseo", "un café", "el cine"]


def test_propose_scenes_falls_back_when_model_gives_garbage():
    state, _ = make_state()
    glue = _glue(state)

    scenes = run(glue.propose_scenes(_FakeSession("no es json"), ANA))

    assert len(scenes) == 3
    assert len(set(scenes)) == 3
    assert all(scene in DATE_SCENES for scene in scenes)


def test_propose_scenes_falls_back_on_http_error():
    state, _ = make_state()
    glue = _glue(state)
    session = _FakeSession(exc=RuntimeError("no hay modelo"))

    scenes = run(glue.propose_scenes(session, ANA))

    assert len(scenes) == 3
    assert all(scene in DATE_SCENES for scene in scenes)


def test_propose_scenes_sends_model_and_low_reasoning_budget():
    state, _ = make_state()
    glue = _glue(state)
    session = _FakeSession(json.dumps({"scenes": ["a", "b"]}))

    run(glue.propose_scenes(session, ANA))

    payload = session.payloads[-1]
    expected_model = os.environ.get("LLM_MODEL", "Qwen3.6-35B-A3B-MTP-UD-IQ3_S")
    assert payload["model"] == expected_model
    assert payload["thinking_budget_tokens"] == 256
    assert "response_format" not in payload
    assert "json_schema" not in payload
    # El límite de reasoning reserva espacio para completar la respuesta JSON.
    assert payload["max_tokens"] == max(DATE_SCENE_MAX_TOKENS, 256 + 512)


def test_evaluate_date_invitation_parses_decision_and_provides_affinity_context():
    state, _ = make_state(affinity={"1": {"points": 2}}, users={"1": {"name": "Ana"}})
    glue = _glue(state)
    session = _FakeSession(
        json.dumps({"decision": "accept", "reply": "¡Sí, vamos!"})
    )

    decision = run(glue.evaluate_date_invitation(session, ANA))

    assert decision.decision == "accept"
    assert decision.reply == "¡Sí, vamos!"
    payload = session.payloads[-1]
    assert "response_format" not in payload
    prompt = " ".join(item["content"] for item in payload["messages"])
    assert "2" in prompt
    assert "umbral" in prompt.lower()


def test_evaluate_date_invitation_fails_closed_on_invalid_json_or_model_error():
    state, _ = make_state()
    glue = _glue(state)

    assert run(glue.evaluate_date_invitation(_FakeSession("not json"), ANA)) is None
    assert run(
        glue.evaluate_date_invitation(_FakeSession(exc=RuntimeError("offline")), ANA)
    ) is None


# --- judge_gift ------------------------------------------------------------


def test_judge_gift_parses_reply_delta_and_event():
    state, _ = make_state(users={"1": {"name": "Ana"}})
    glue = _glue(state)
    content = json.dumps(
        {"reply": "Gracias por las flores", "affinity_delta": 3,
         "affinity_event": "me encantan las rosas"}
    )

    judged = run(glue.judge_gift(_FakeSession(content), "rosas", ANA, []))

    assert judged == ("Gracias por las flores", 3, "me encantan las rosas")


def test_judge_gift_zeroes_delta_without_reason():
    state, _ = make_state()
    glue = _glue(state)
    content = json.dumps(
        {"reply": "Vale", "affinity_delta": 4, "affinity_event": "none"}
    )

    reply, delta, event = run(glue.judge_gift(_FakeSession(content), "piedra", ANA))

    assert reply == "Vale"
    assert delta == 0
    assert event == "none"


def test_judge_gift_returns_none_on_model_failure():
    state, _ = make_state()
    glue = _glue(state)
    session = _FakeSession(exc=RuntimeError("boom"))

    assert run(glue.judge_gift(session, "rosas", ANA, [])) is None


def test_judge_gift_clamps_delta_to_the_maximum():
    state, _ = make_state()
    glue = _glue(state)
    content = json.dumps(
        {"reply": "Wow", "affinity_delta": 999, "affinity_event": "un detallazo"}
    )

    _reply, delta, _event = run(glue.judge_gift(_FakeSession(content), "coche", ANA))

    assert delta <= 8


def test_judge_gift_sends_model_and_low_reasoning_budget():
    state, _ = make_state()
    glue = _glue(state)
    content = json.dumps(
        {"reply": "Gracias", "affinity_delta": 2, "affinity_event": "detalle"}
    )
    session = _FakeSession(content)

    run(glue.judge_gift(session, "rosas", ANA, []))

    payload = session.payloads[-1]
    expected_model = os.environ.get("LLM_MODEL", "Qwen3.6-35B-A3B-MTP-UD-IQ3_S")
    assert payload["model"] == expected_model
    assert payload["thinking_budget_tokens"] == 256
    assert "response_format" not in payload
    assert "json_schema" not in payload


# --- citas exclusivas: expiración y avisos --------------------------------


def test_expire_stale_dates_closes_and_logs():
    state, counters = make_state(users={"1": {"name": "Ana"}})
    session = new_date_session("paseo", 40, now=NOW)
    state.dates["1"] = session
    glue = _glue(state)

    expired = glue.expire_stale_dates(now=NOW + DATE_MAX_SECONDS + 1)

    assert expired == ["1"]
    assert "1" not in state.dates
    assert session["state"] == "closed"
    assert counters["dates"] == 1


def test_expire_stale_dates_keeps_active_dates():
    state, _ = make_state()
    state.dates["1"] = new_date_session("paseo", 40, now=NOW)
    glue = _glue(state)

    assert glue.expire_stale_dates(now=NOW + 1) == []
    assert "1" in state.dates


def test_busy_date_owner_returns_other_active_session():
    state, _ = make_state()
    state.dates["2"] = new_date_session("paseo", 40, now=REAL_NOW)
    glue = _glue(state)

    owner_id, session = glue.busy_date_owner(exclude_id=1)

    assert owner_id == "2"
    assert session is state.dates["2"]


def test_busy_date_owner_skips_self_and_closed():
    state, _ = make_state()
    state.dates["1"] = new_date_session("paseo", 40, now=REAL_NOW)
    state.dates["3"] = new_date_session("cine", 40, now=REAL_NOW)
    state.dates["3"]["state"] = "closed"
    glue = _glue(state)

    assert glue.busy_date_owner(exclude_id=1) == (None, None)


def test_date_busy_text_mentions_partner_and_time_left():
    state, _ = make_state(users={"2": {"name": "Bea"}})
    session = new_date_session("paseo", 40, now=NOW)
    glue = _glue(state)

    text = glue.date_busy_text("2", session, now=NOW)

    assert "Bea" in text
    assert "cita" in text


def test_notify_busy_sends_once_then_respects_cooldown():
    state, _ = make_state(users={"2": {"name": "Bea"}})
    state.dates["2"] = new_date_session("paseo", 40, now=REAL_NOW)
    glue = _glue(state)
    channel = _FakeChannel()

    run(glue.notify_busy(channel, ANA, now=REAL_NOW))
    run(glue.notify_busy(channel, ANA, now=REAL_NOW + 5))

    assert len(channel.sent) == 1
    assert "Bea" in channel.sent[0]


# --- diario ----------------------------------------------------------------


def test_add_diary_reflection_saves_once_and_dedups():
    state, counters = make_state(users={"1": {"name": "Ana"}})
    glue = _glue(state)

    assert glue.add_diary_reflection(1, "Hoy me sentí muy feliz", now=NOW) is True
    assert counters["diary"] == 1
    assert state.diary[-1]["kind"] == "reflection"

    # Texto idéntico → duplicado descartado.
    assert glue.add_diary_reflection(1, "Hoy me sentí muy feliz", now=NOW + 10) is False


def test_add_diary_reflection_respects_min_interval():
    state, _ = make_state(users={"1": {"name": "Ana"}})
    glue = _glue(state)

    assert glue.add_diary_reflection(1, "Primera", now=NOW) is True
    assert glue.add_diary_reflection(1, "Otra cosa", now=NOW + 1) is False


# --- afinidad y turno de cita ---------------------------------------------


def test_affinity_footer_text_includes_points_and_level():
    state, _ = make_state(affinity={"1": {"points": 25}})
    glue = _glue(state)

    text = glue.affinity_footer_text(1, "Ana")

    assert "25 pts" in text
    assert "Amiga" in text
    assert "Ana" in text


def test_process_date_turn_continue_saves_state():
    state, counters = make_state(users={"1": {"name": "Ana"}})
    session = new_date_session("paseo", 40, now=NOW)
    state.dates["1"] = session
    glue = _glue(state)
    channel = _FakeChannel()

    event = run(
        glue.process_date_turn(
            channel,
            ANA,
            session,
            text="hola",
            delta=0,
            points=40,
            date_decision="continue",
            date_reason="none",
            last_chance_result="none",
            now=NOW,
        )
    )

    assert event == "continue"
    assert session["turns"] == 1
    assert "1" in state.dates
    assert counters["dates"] == 1
    assert channel.sent == []


def test_gift_reply_cannot_claim_a_partner_that_is_not_confirmed():
    state, _ = make_state(users={"1": {"name": "Ana"}}, world={"season": 1})
    glue = _glue(state)
    content = json.dumps(
        {
            "reply": "Gracias... ya somos pareja, ¿vale?",
            "affinity_delta": 3,
            "affinity_event": "me ha gustado",
        }
    )

    reply, _delta, _event = run(
        glue.judge_gift(_FakeSession(content), "rosas", ANA, [])
    )

    assert "pareja" not in reply.lower()
