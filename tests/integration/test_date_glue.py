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
from airi.domain.constants import (
    DATE_MAX_SECONDS,
    DATE_QUESTION_TIMEOUT,
    DATE_SCENE_TIMEOUT,
)
from airi.domain.dates import new_date_session
from airi.domain.prompts import GIFT_JUDGE_SCHEMA
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
        state, llm_url="http://x", request_timeout=5
    )


# --- escena por texto libre -------------------------------------------------

OPTIONS = [
    {"label": "Cómo me escuchas", "action": "la escuchas atentamente",
     "up_chance": 1.0, "delta_up": 20, "delta_down": -5},
    {"label": "Eres guapa", "action": "le dices que es guapa",
     "up_chance": 0.0, "delta_up": 5, "delta_down": -22},
]


def test_request_scene_marks_pending_scene():
    state, _ = make_state()
    glue = _glue(state)

    text = glue.request_scene(1, now=NOW)

    assert "Dime solo el lugar" in text
    assert "solo el nombre del lugar" in text
    assert glue.pending_scene(1, now=NOW) is True


def test_take_pending_scene_consumes_request():
    state, _ = make_state()
    glue = _glue(state)
    glue.request_scene(1, now=NOW)

    assert glue.take_pending_scene(1, now=NOW) is True
    assert glue.pending_scene(1, now=NOW) is False
    assert glue.take_pending_scene(1, now=NOW) is False


def test_pending_scene_expires_after_timeout():
    state, _ = make_state()
    glue = _glue(state)
    glue.request_scene(1, now=NOW)

    assert glue.pending_scene(1, now=NOW + DATE_SCENE_TIMEOUT + 1) is False


def test_clear_scene_request_discards_pending():
    state, _ = make_state()
    glue = _glue(state)
    glue.request_scene(1, now=NOW)

    glue.clear_scene_request(1)

    assert glue.pending_scene(1, now=NOW) is False


def test_expire_scene_requests_returns_expired_uids():
    state, _ = make_state()
    glue = _glue(state)
    glue.request_scene(1, now=NOW)
    glue.request_scene(2, now=NOW)

    expired = glue.expire_scene_requests(now=NOW + DATE_SCENE_TIMEOUT + 1)

    assert sorted(expired) == ["1", "2"]
    assert glue.expire_scene_requests(now=NOW) == []


# --- pregunta decisiva -----------------------------------------------------

def _date_with_question(state, uid="1", now=NOW, asked_at=None):
    session = new_date_session("paseo", 40, now=now)
    session["turns"] = 3
    session["question"] = {"text": "¿Qué eliges?", "options": OPTIONS}
    session["question_used"] = True
    session["question_pending"] = True
    session["question_asked_at"] = now if asked_at is None else asked_at
    state.dates[uid] = session
    return session


def test_resolve_question_rolls_and_returns_result():
    state, _ = make_state()
    session = _date_with_question(state)
    glue = _glue(state)

    result = glue.resolve_question(session, 0)

    assert result["index"] == 0
    assert result["label"] == "Cómo me escuchas"
    assert result["win"] is True
    assert result["delta"] == 20
    assert result["hard_fail"] is False


def test_resolve_question_hard_fail_on_bad_option():
    state, _ = make_state()
    session = _date_with_question(state)
    glue = _glue(state)

    result = glue.resolve_question(session, 1)

    assert result["win"] is False
    assert result["delta"] == -22
    assert result["hard_fail"] is True  # -22 <= -20 → última oportunidad


def test_resolve_question_invalid_index_returns_none():
    state, _ = make_state()
    session = _date_with_question(state)
    glue = _glue(state)

    assert glue.resolve_question(session, 5) is None


def test_apply_question_result_applies_affinity_and_clears_pending():
    state, counters = make_state(
        affinity={"1": {"points": 40, "last_interaction": NOW,
                        "last_gain": 0.0, "milestones": []}}
    )
    session = _date_with_question(state)
    glue = _glue(state)

    applied = glue.apply_question_result(
        session, {"index": 0, "win": True, "delta": 20,
                  "label": "Cómo me escuchas", "hard_fail": False},
        user_id=1, now=NOW,
    )

    assert applied == 20
    assert state.entry_points(1) == 60
    assert session["question_pending"] is False
    assert "force_crisis" not in session
    assert counters["dates"] == 1


def test_apply_question_result_marks_force_crisis_on_hard_fail():
    state, _ = make_state()
    session = _date_with_question(state)
    glue = _glue(state)

    glue.apply_question_result(
        session, {"index": 1, "win": False, "delta": -22,
                  "label": "Eres guapa", "hard_fail": True},
        user_id=1, now=NOW,
    )

    assert session["force_crisis"] is True
    assert session["question_pending"] is False


def test_expire_question_clears_pending_without_affinity():
    state, counters = make_state()
    session = _date_with_question(state)
    glue = _glue(state)

    glue.expire_question(1)

    assert session["question_pending"] is False
    assert session["question_used"] is True  # la pregunta ya se gastó
    assert counters["dates"] == 1  # se persistió


def test_expire_stale_questions_sweeps_orphans_only():
    state, _ = make_state()
    # Huérfana: pendiente desde hace más del timeout (vista perdida).
    _date_with_question(state, uid="1", asked_at=NOW - DATE_QUESTION_TIMEOUT - 10)
    # Fresca: la vista sigue viva.
    _date_with_question(state, uid="2", asked_at=NOW - 5)
    # Sin pedir: ni la toca.
    fresh = new_date_session("paseo", 40, now=NOW)
    state.dates["3"] = fresh
    glue = _glue(state)

    expired = glue.expire_stale_questions(now=NOW)

    assert expired == ["1"]
    assert state.dates["1"]["question_pending"] is False
    assert state.dates["2"]["question_pending"] is True
    assert fresh["question_pending"] is False


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


def test_judge_gift_sends_model_and_disables_thinking():
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
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["response_format"]["json_schema"]["name"] == "structured_output"
    assert payload["response_format"]["json_schema"]["schema"] == GIFT_JUDGE_SCHEMA
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


def test_process_date_turn_summarizes_on_close():
    """Al cerrar con `http_session`, el glue pide el resumen y lo deja en diario."""
    state, _ = make_state(users={"1": {"name": "Ana"}})
    session = new_date_session("una cena a la luz de las velas", 40, now=NOW)
    session["turns"] = 4
    session["history"] = [{"role": "user", "content": "Ana: llegué pronto"}]
    state.dates["1"] = session
    glue = _glue(state)
    channel = _FakeChannel()
    http = _FakeSession("Recordaré esta cena con Ana toda la vida.")

    event = run(
        glue.process_date_turn(
            channel,
            ANA,
            session,
            http_session=http,
            text="adiós, nos vemos",
            delta=0,
            points=40,
            date_decision="continue",
            date_reason="none",
            last_chance_result="none",
            now=NOW,
        )
    )

    assert event == "ending"
    assert "1" not in state.dates
    dates = [e for e in state.diary if e.get("kind") == "date"]
    assert dates and dates[-1]["text"] == "Recordaré esta cena con Ana toda la vida."
    # El resumen se pidió como texto libre (sin schema JSON).
    payload = http.payloads[-1]
    assert "response_format" not in payload
