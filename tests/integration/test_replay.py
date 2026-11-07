"""Regresión del replay: fixtures de trazas y paso de cita fiel."""

from __future__ import annotations

import asyncio
import os

import pytest

from airi.domain.dates import new_date_session
from airi.observability import replay as replay_module
from airi.observability.llm_payload_capture import LocalLlmPayloadCapture
from airi.observability.replay import replay_behavioral, replay_trace
from airi.observability.replay_capture import write_web_capture
from airi.observability.trace import TurnEvent, save_turn_trace
from airi.ports.llm import LLMCallContext
from airi.services.conversation import ConversationService, TurnContext
from airi.services.date_service import DateService
from airi.testing import FakeLLM, FakeNotifier, FakeSearch, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")
FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "traces", "affinity_delta_without_reason.json"
)


def run(coro):
    return asyncio.run(coro)


def test_affinity_delta_without_reason_fixture_replays():
    result = run(replay_trace(FIXTURE))
    assert result.reproducible
    assert result.matches_original, result.checks
    # delta 3 sin motivo (affinity_event="none") no debe aplicarse.
    assert result.affinity_delta_applied == 0
    assert result.coverage == "partial"
    assert "search_decision" in result.not_evaluated


def test_replay_hydrates_response_sidecar_without_inline_raw(tmp_path, monkeypatch):
    raw = llm_json("respuesta desde artefacto")
    capture = LocalLlmPayloadCapture(tmp_path / "artifacts")
    context = LLMCallContext("sidecar-cid", "primary", 1)
    stored = run(capture.capture_response(context, {
        "content": raw, "reasoning_content": "ignored during replay",
    }))
    event = TurnEvent(
        correlation_id="sidecar-cid", user_id="42", user_name="David",
        messages_in=[{"author": "David", "text": "hola"}],
        history_in=[{"role": "user", "content": "hola"}],
        raw_llm=raw,
        final_reply="respuesta desde artefacto",
    )
    event.llm_calls = [{"call_index": 1, "response_capture": {
        "status": "captured", "artifact_ref": stored.artifact_ref,
        "sha256": stored.sha256,
    }}]
    path = save_turn_trace(event, str(tmp_path / "traces"))
    monkeypatch.setenv("TRACE_LLM_ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    # Simulate a newly serialized trace: summary has no inline LLM response.
    data = __import__("json").loads(open(path, encoding="utf-8").read())
    data.pop("raw_llm", None)
    open(path, "w", encoding="utf-8").write(__import__("json").dumps(data))
    replayed = run(replay_trace(path))

    assert replayed.reproducible
    assert replayed.checks["reply"]


def test_replay_active_turn_preserves_session_schema_and_stay_active(tmp_path):
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("Sigo en la conversación.", stay_active=True)])
    svc = ConversationService(llm=llm, state=state, clock=lambda: NOW)
    generated = run(svc.run_turn(
        DAVID,
        [(DAVID, "¿Sigues por aquí?")],
        TurnContext(conversation_mode="active", now=NOW),
    ))
    # The persisted event's kind is the runtime session kind, independent of
    # the internal user-message trigger used to construct this fixture.
    generated.trace.kind = "active"
    path = save_turn_trace(generated.trace, str(tmp_path))

    replayed = run(replay_trace(path))

    assert generated.trace.kind == "active"
    assert replayed.conversation_mode == "active"
    assert replayed.stay_active is True
    assert replayed.checks["session_schema"] is True
    assert replayed.checks["stay_active"] is True
    assert replayed.matches_original


def _golden_date_trace(tmp_path, *, capture_date_event):
    """Genera una traza de cita; opcionalmente captura el paso de DateService."""
    session = new_date_session("una cena a la luz de las velas", 10, now=NOW)
    state, _ = make_state(dates={"42": session})
    llm = FakeLLM(replies=[
        llm_json("qué bien", affinity_delta=2, affinity_event="cena")
    ])
    svc = ConversationService(
        llm=llm, state=state, notifier=FakeNotifier(), clock=lambda: NOW,
        date_delta_max=8,
    )
    result = run(svc.run_turn(
        DAVID, [(DAVID, "qué rica la cena")], TurnContext()
    ))

    if capture_date_event:
        date_svc = DateService(state=state, notifier=None, clock=lambda: NOW)
        result.trace.date_event = run(date_svc.process_turn(
            state.dates["42"],
            user=DAVID,
            text="qué rica la cena",
            delta=result.affinity_delta,
            points=state.entry_points(DAVID.id),
            date_decision=result.date_decision,
            date_reason=result.date_reason,
            last_chance_result=result.last_chance_result,
            now=NOW,
        ))

    return save_turn_trace(result.trace, str(tmp_path))


def test_replay_date_turn_verifies_date_event(tmp_path):
    path = _golden_date_trace(tmp_path, capture_date_event=True)
    result = run(replay_trace(path))

    assert result.matches_original, result.checks
    assert result.checks["date_event"] is True
    assert result.date_event == "continue"


def test_replay_date_turn_without_date_event_is_tolerated(tmp_path):
    path = _golden_date_trace(tmp_path, capture_date_event=False)
    result = run(replay_trace(path))

    assert "date_event" not in result.checks
    assert result.matches_original, result.checks


def test_behavioral_replay_reports_captured_empty_and_query_match(tmp_path, monkeypatch):
    trace = TurnEvent(
        correlation_id="behavioral-empty", user_id="42", user_name="David",
        messages_in=[{"author": "David", "text": "¿qué tiempo hace hoy?"}],
        history_in=[{"role": "user", "content": "¿qué tiempo hace hoy?"}],
        final_reply="Hoy hace sol.", raw_llm="{}",
    )
    trace_path = save_turn_trace(trace, str(tmp_path / "traces"))
    capture_path = tmp_path / "capture.json"
    write_web_capture(
        capture_path, correlation_id=trace.correlation_id, status="empty",
        query="weather today",
    )
    llm = FakeLLM(
        replies=[llm_json("No encontré resultados actuales.")],
        tool_calls=[[{"name": "buscar_web", "arguments": {
            "query": "weather today", "motivo": "verificar pronóstico",
        }}]],
    )
    monkeypatch.setattr(replay_module, "build_llm", lambda _session: llm)
    monkeypatch.setenv("AIRI_WEB_SEARCH", "true")

    task_context = {
        "goal": "consultar el pronóstico", "constraints": ["no inventar datos"],
        "progress": "buscando", "next_step": "resumir",
    }
    result = run(replay_behavioral(trace_path, capture_path, task_context=task_context))

    assert result.mode == "behavioral"
    assert result.checks["search_decision"]["status"] == "passed"
    assert result.checks["search_query"]["status"] == "passed"
    assert result.checks["search_result"]["status"] == "captured_empty"
    assert result.checks["grounding"]["status"] == "evaluated"
    assert result.checks["reply"]["status"] == "failed"
    assert result.checks["task_context"]["status"] == "provided"
    assert "consultar el pronóstico" in llm.last_system_prompt


def test_behavioral_replay_does_not_use_evidence_for_different_query(tmp_path, monkeypatch):
    trace = TurnEvent(
        correlation_id="behavioral-mismatch", user_id="42", user_name="David",
        messages_in=[{"author": "David", "text": "¿qué tiempo hace hoy?"}],
        history_in=[{"role": "user", "content": "¿qué tiempo hace hoy?"}],
        final_reply="Hoy hace sol.", raw_llm="{}",
    )
    trace_path = save_turn_trace(trace, str(tmp_path / "traces"))
    capture_path = tmp_path / "capture.json"
    write_web_capture(
        capture_path, correlation_id=trace.correlation_id, status="results",
        query="weather today", results=[{"title": "Forecast", "snippet": "Sunny"}],
    )
    llm = FakeLLM(
        replies=[llm_json("No tengo esa evidencia.")],
        tool_calls=[[{"name": "buscar_web", "arguments": {
            "query": "weather tomorrow", "motivo": "consulta nueva",
        }}]],
    )
    monkeypatch.setattr(replay_module, "build_llm", lambda _session: llm)
    monkeypatch.setenv("AIRI_WEB_SEARCH", "true")

    result = run(replay_behavioral(trace_path, capture_path))

    assert result.checks["search_decision"]["status"] == "passed"
    assert result.checks["search_query"]["status"] == "failed"
    assert result.checks["search_result"]["status"] == "capture_mismatch"
    assert result.checks["grounding"]["status"] == "not_evaluated"
    assert result.checks["reply"]["status"] == "failed"


def test_behavioral_replay_uses_matching_captured_results(tmp_path, monkeypatch):
    trace = TurnEvent(
        correlation_id="behavioral-results", user_id="42", user_name="David",
        messages_in=[{"author": "David", "text": "¿tiempo?"}],
        history_in=[{"role": "user", "content": "¿tiempo?"}],
        final_reply="Va a llover.", raw_llm="{}",
    )
    trace_path = save_turn_trace(trace, str(tmp_path / "traces"))
    capture_path = tmp_path / "capture.json"
    write_web_capture(
        capture_path, correlation_id=trace.correlation_id, status="results",
        query="weather today",
        results=[{"title": "Forecast", "snippet": "Rain expected"}],
    )
    llm = FakeLLM(
        replies=[llm_json("Parece que va a llover.")],
        tool_calls=[[{"name": "buscar_web", "arguments": {
            "query": "weather today", "motivo": "consultar pronóstico",
        }}]],
    )
    monkeypatch.setattr(replay_module, "build_llm", lambda _session: llm)
    monkeypatch.setenv("AIRI_WEB_SEARCH", "true")

    result = run(replay_behavioral(trace_path, capture_path))

    assert result.checks["search_result"]["status"] == "captured_results"
    assert result.checks["grounding"]["status"] == "evaluated"
    assert any("Rain expected" in call["messages"][0]["content"] for call in llm.calls)


def test_behavioral_llm_failure_is_an_execution_error(tmp_path, monkeypatch):
    trace = TurnEvent(
        correlation_id="behavioral-error", user_id="42", user_name="David",
        messages_in=[{"author": "David", "text": "¿tiempo?"}],
        history_in=[{"role": "user", "content": "¿tiempo?"}], raw_llm="{}",
    )
    trace_path = save_turn_trace(trace, str(tmp_path / "traces"))
    capture_path = tmp_path / "capture.json"
    write_web_capture(
        capture_path, correlation_id=trace.correlation_id, status="not_requested",
    )

    def fail(_session):
        raise RuntimeError("LLM indisponible")

    monkeypatch.setattr(replay_module, "build_llm", fail)

    with pytest.raises(RuntimeError, match="LLM indisponible"):
        run(replay_behavioral(trace_path, capture_path))


def test_deterministic_replay_never_constructs_live_llm(monkeypatch):
    def unexpected(_session):
        raise AssertionError("el modo determinista no debe crear un cliente LLM")

    monkeypatch.setattr(replay_module, "build_llm", unexpected)
    result = run(replay_trace(FIXTURE))
    assert result.reproducible
    assert "search_decision" in result.not_evaluated


def test_live_web_permission_requires_key_before_client_creation(tmp_path, monkeypatch):
    trace = TurnEvent(correlation_id="live-key", user_id="42", raw_llm="{}")
    path = save_turn_trace(trace, str(tmp_path))
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    async def never_create_session(*args, **kwargs):
        raise AssertionError("no debe inicializar clientes sin clave de web live")

    monkeypatch.setattr(replay_module.aiohttp, "ClientSession", never_create_session)

    with pytest.raises(ValueError, match="BRAVE_API_KEY"):
        run(replay_module.run_live_trace(path, web_live=True))


def test_live_repeat_keeps_prior_sample_when_later_sample_fails(tmp_path, monkeypatch):
    trace = TurnEvent(
        correlation_id="live-repeat", user_id="42", user_name="David",
        messages_in=[{"author": "David", "text": "hola"}],
        history_in=[{"role": "user", "content": "hola"}], raw_llm="{}",
    )
    path = save_turn_trace(trace, str(tmp_path))
    successful_llm = FakeLLM(replies=[llm_json("Hola.")])
    calls = iter([successful_llm, RuntimeError("backend indisponible")])

    def build(_session):
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(replay_module, "build_llm", build)

    samples = run(replay_module.run_live_trace(path, repeat=2))

    assert samples[0]["sample"] == 1
    assert samples[0]["result"].reply == "Hola."
    assert samples[1] == {"sample": 2, "error": {"type": "RuntimeError"}}


def test_live_mode_keeps_search_disabled_without_web_permission(tmp_path, monkeypatch):
    trace = TurnEvent(
        correlation_id="live-no-web", user_id="42", user_name="David",
        messages_in=[{"author": "David", "text": "busca el clima"}],
        history_in=[{"role": "user", "content": "busca el clima"}], raw_llm="{}",
    )
    path = save_turn_trace(trace, str(tmp_path))
    llm = FakeLLM(replies=[llm_json("Puedo ayudarte.")])
    monkeypatch.setattr(replay_module, "build_llm", lambda _session: llm)

    samples = run(replay_module.run_live_trace(path))

    assert len(samples) == 1
    assert not llm.decision_calls


def test_live_replay_applies_requested_experimental_prompt_variant(tmp_path, monkeypatch):
    trace = TurnEvent(
        correlation_id="live-prompt-variant", user_id="42", user_name="David",
        messages_in=[{"author": "David", "text": "hola Airi"}],
        history_in=[{"role": "user", "content": "hola Airi"}], raw_llm="{}",
    )
    path = save_turn_trace(trace, str(tmp_path))
    llm = FakeLLM(replies=[llm_json("Hola.")])
    monkeypatch.setattr(replay_module, "build_llm", lambda _session: llm)

    samples = run(replay_module.run_live_trace(
        path, prompt_variant="gif_priority_candidate"
    ))

    assert samples[0]["result"].reply == "Hola."
    assert llm.last_system_prompt.count("=== REACCIONES VISUALES Y SELECCIÓN DE GIF ===") == 1
    assert "wave` — Saludar o despedirse moviendo la mano" in llm.last_system_prompt
    assert "Ante un saludo o presentación, elige wave" not in llm.last_system_prompt


def test_live_replay_applies_decision_light_prompt_variant(tmp_path, monkeypatch):
    trace = TurnEvent(
        correlation_id="live-decision-light", user_id="42", user_name="David",
        messages_in=[{"author": "David", "text": "hola Airi"}],
        history_in=[{"role": "user", "content": "hola Airi"}], raw_llm="{}",
    )
    path = save_turn_trace(trace, str(tmp_path))
    llm = FakeLLM(replies=[llm_json("Hola.")])
    monkeypatch.setattr(replay_module, "build_llm", lambda _session: llm)

    samples = run(replay_module.run_live_trace(
        path, prompt_variant="decision_light_candidate"
    ))

    assert samples[0]["result"].reply == "Hola."
    assert "El GIF no necesita coincidir con mood.label" in llm.last_system_prompt
    assert "shy representa vergüenza o pudor visibles" in llm.last_system_prompt
    assert "no son obligatorias" in llm.last_system_prompt


def test_live_search_client_is_used_only_with_explicit_permission(tmp_path, monkeypatch):
    from airi.adapters import brave_search

    trace = TurnEvent(
        correlation_id="live-web", user_id="42", user_name="David",
        messages_in=[{"author": "David", "text": "busca el clima"}],
        history_in=[{"role": "user", "content": "busca el clima"}], raw_llm="{}",
    )
    path = save_turn_trace(trace, str(tmp_path))
    llm = FakeLLM(
        replies=[llm_json("No encontré datos.")],
        tool_calls=[[{"name": "buscar_web", "arguments": {
            "query": "weather", "motivo": "petición explícita",
        }}]],
    )
    search = FakeSearch()
    constructed = []

    def make_search(api_key, session):
        constructed.append((api_key, session))
        return search

    monkeypatch.setattr(brave_search, "BraveSearchClient", make_search)
    monkeypatch.setattr(replay_module, "build_llm", lambda _session: llm)
    monkeypatch.setenv("BRAVE_API_KEY", "test-key")

    samples = run(replay_module.run_live_trace(path, web_live=True))

    assert constructed and constructed[0][0] == "test-key"
    assert llm.decision_calls
    assert search.queries == ["weather"]
    assert samples[0]["result"].reply == "No encontré datos."
