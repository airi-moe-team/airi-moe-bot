"""Tests de observabilidad: instrumentación de run_turn y replay.

La unidad `TurnEvent` (serialización, aliases, recortes) se prueba en
`tests/unit/test_events.py`; aquí se cubre el servicio y el replay.
"""

import asyncio

from airi.observability.replay import check_trace
from airi.observability.trace import (
    TurnTrace,
    load_turn_trace,
    save_turn_trace,
)
from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeLLM, FakeNotifier, FakeSearch, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")


def run(coro):
    return asyncio.run(coro)


def make_service(llm, state, **kw):
    return ConversationService(
        llm=llm, state=state, clock=lambda: NOW, **kw
    )


# ---------------------------------------------------------------------------
# Servicio: la traza viaja en TurnResult y el hook on_trace se llama
# ---------------------------------------------------------------------------


def test_run_turn_attaches_trace_with_cid_and_timings():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("¡Hola!", affinity_delta=1,
                                     affinity_event="saludo")])
    svc = make_service(llm, state, notifier=FakeNotifier())
    seen = []

    result = run(svc.run_turn(
        DAVID, [(DAVID, "hola")], TurnContext(correlation_id="cid123",
                                              on_trace=seen.append),
    ))

    assert result.trace is not None
    assert result.trace.correlation_id == "cid123"
    assert seen == [result.trace]
    trace = result.trace
    assert trace.user_id == "42"
    assert trace.prompt_system  # el prompt enviado se captura
    assert trace.raw_llm is not None
    assert trace.parsed["reply"] == "¡Hola!"
    assert trace.reply == "¡Hola!"
    assert trace.affinity_before == 0
    assert trace.affinity_after == 1
    assert trace.turn_ms >= 0
    assert trace.timings_ms["llm_ms"] >= 0


def test_run_turn_generates_cid_when_missing():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("hola")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.trace.correlation_id
    assert len(result.trace.correlation_id) == 12


def test_run_turn_trace_captures_search_and_grounding():
    state, _ = make_state()
    search = FakeSearch(result="Fuente 1: BTC\nURL: https://x\nResumen: 30k")
    llm = FakeLLM(replies=["precio bitcoin", llm_json("ronda los 30k")])
    svc = make_service(llm, state, search=search, notifier=FakeNotifier())

    result = run(svc.run_turn(
        DAVID, [(DAVID, "búscame en internet el precio de bitcoin")], TurnContext(),
    ))

    assert result.trace.search_query == "precio bitcoin"
    assert result.trace.web_context is not None
    assert result.trace.grounded is True
    assert result.trace.timings_ms["search_ms"] >= 0


def test_run_turn_broken_hook_does_not_break_turn():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("hola")])

    def boom(trace):
        raise RuntimeError("hook roto")

    svc = make_service(llm, state, notifier=FakeNotifier())
    result = run(svc.run_turn(DAVID, [(DAVID, "hola")],
                              TurnContext(on_trace=boom)))

    assert result.reply == "hola"


def test_run_turn_trace_repeated_answer_is_not_skipped():
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "David: hola"},
        {"role": "assistant", "content": "Ya te dije hola antes"},
    ]
    llm = FakeLLM(replies=[llm_json("Ya te dije hola antes")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.skipped is False
    assert result.reply == "Ya te dije hola antes"
    assert result.trace is not None
    assert result.trace.skipped is False
    assert result.trace.raw_llm is not None


# ---------------------------------------------------------------------------
# Replay: goldens generados con el propio servicio
# ---------------------------------------------------------------------------


def _golden_trace(tmp_path, name, llm_replies, messages, **state_kw):
    """Genera un JSON golden ejecutando el servicio con fakes."""
    state, _ = make_state(**state_kw)
    llm = FakeLLM(replies=list(llm_replies))
    svc = make_service(llm, state, notifier=FakeNotifier(),
                       search=FakeSearch(result=None))
    result = run(svc.run_turn(DAVID, messages, TurnContext()))
    assert result.trace is not None
    path = save_turn_trace(result.trace, str(tmp_path / name))
    assert path is not None
    return path


def test_replay_simple_turn_matches(tmp_path):
    path = _golden_trace(
        tmp_path, "simple",
        [llm_json("¡Hola, David!", affinity_delta=2, affinity_event="saludo")],
        [(DAVID, "hola")],
    )
    ok, report = check_trace(load_turn_trace(path))
    assert report["checks"]["reply"] is True
    assert report["checks"]["affinity_applied"] is True
    assert ok is True


def test_replay_turn_with_memory_and_gif_matches(tmp_path):
    path = _golden_trace(
        tmp_path, "memgif",
        [llm_json("¡Siii~!", gif="happy", memory="Le gusta el ramen",
                  affinity_delta=1, affinity_event="alegría")],
        [(DAVID, "traigo ramen")],
    )
    ok, report = check_trace(load_turn_trace(path))
    assert ok is True, report


def test_replay_detects_divergence(tmp_path):
    path = _golden_trace(
        tmp_path, "div",
        [llm_json("original", affinity_delta=1, affinity_event="x")],
        [(DAVID, "hola")],
    )
    trace = load_turn_trace(path)
    trace.reply = "MANIPULADA"
    ok, report = check_trace(trace)
    assert ok is False
    assert report["checks"]["reply"] is False


def test_replay_without_raw_is_not_reproducible(tmp_path):
    trace = TurnTrace(correlation_id="n", user_id="42", final_reply="hola")
    path = save_turn_trace(trace, str(tmp_path), keep_raw=False)
    ok, report = check_trace(load_turn_trace(path))
    assert ok is False
    assert report["reproducible"] is False


def test_replay_repeated_answer_matches(tmp_path):
    state_kw = {"histories": {0: [
        {"role": "user", "content": "David: hola"},
        {"role": "assistant", "content": "Ya te dije hola antes"},
    ]}}
    path = _golden_trace(
        tmp_path, "skip",
        [llm_json("Ya te dije hola antes")],
        [(DAVID, "hola")],
        **state_kw,
    )
    ok, report = check_trace(load_turn_trace(path))
    assert ok is True, report


def test_replay_in_date_turn_matches(tmp_path):
    from airi.domain.dates import new_date_session as _nds
    session = _nds("cena", 10, now=NOW)
    path = _golden_trace(
        tmp_path, "date",
        [llm_json("qué bien", affinity_delta=2, affinity_event="cena",
                  date_decision="continue")],
        [(DAVID, "qué rica la cena")],
        dates={"42": session},
    )
    ok, report = check_trace(load_turn_trace(path))
    assert ok is True, report
