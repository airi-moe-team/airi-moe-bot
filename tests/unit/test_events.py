"""Tests unitarios de TurnEvent: serialización, aliases y compatibilidad v1.

Los tests de instrumentación de `run_turn` y de replay viven en
`tests/test_observability.py` y `tests/integration/test_replay.py`; aquí solo
se ejercita la unidad `TurnEvent` sin servicio ni I/O de red.
"""

from __future__ import annotations

import json

from airi.observability.trace import (
    MAX_RAW_LLM_CHARS,
    TurnEvent,
    TurnTrace,
    load_turn_trace,
    save_turn_trace,
    trace_path,
)

# ---------------------------------------------------------------------------
# Tipo y valores por defecto
# ---------------------------------------------------------------------------


def test_turn_trace_is_alias_of_turn_event():
    assert TurnTrace is TurnEvent


def test_default_kind_is_message():
    ev = TurnEvent()
    assert ev.kind == "message"
    assert ev.affinity_event == "none"
    assert ev.date_decision == "continue"


def test_review_telemetry_round_trips_and_old_trace_defaults():
    ev = TurnEvent(
        review_on_topic=False,
        review_issues=[{"kind": "off_topic", "evidence": "literal"}],
        review_ms=123,
        repair_exhausted=True,
    )
    loaded = TurnEvent.from_dict(json.loads(ev.to_json()))
    assert loaded.review_on_topic is False
    assert loaded.review_issues == [{"kind": "off_topic", "evidence": "literal"}]
    assert loaded.review_ms == 123
    assert loaded.repair_exhausted is True

    old = TurnEvent.from_dict({"correlation_id": "old"})
    assert old.review_on_topic is None
    assert old.review_issues == []
    assert old.review_ms is None
    assert old.repair_exhausted is False


def test_list_fields_are_independent_between_instances():
    a = TurnEvent()
    b = TurnEvent()
    a.errors.append({"type": "X"})
    a.notes.append("nota")
    assert b.errors == []
    assert b.notes == []


# ---------------------------------------------------------------------------
# Aliases v1 (reply / turn_ms)
# ---------------------------------------------------------------------------


def test_reply_and_turn_ms_aliases_are_writable():
    ev = TurnEvent()
    ev.reply = "hola"
    ev.turn_ms = 123
    assert ev.final_reply == "hola"
    assert ev.total_latency_ms == 123


def test_reply_and_turn_ms_aliases_are_readable():
    ev = TurnEvent(final_reply="x", total_latency_ms=7)
    assert ev.reply == "x"
    assert ev.turn_ms == 7


def test_from_dict_translates_legacy_keys():
    ev = TurnEvent.from_dict({"correlation_id": "old", "reply": "hola", "turn_ms": 42})
    assert ev.final_reply == "hola"
    assert ev.total_latency_ms == 42
    assert ev.time_context == {}


def test_time_context_round_trips_without_message_content():
    source = {
        "enabled": True,
        "timezone": "Europe/Madrid",
        "local_iso": "2026-10-27T03:14",
        "weekday": "martes",
        "bucket": "madrugada",
        "minutes_since_user": 12,
        "minutes_since_channel": None,
    }
    ev = TurnEvent(time_context=source)
    restored = TurnEvent.from_dict(ev.to_dict())
    assert restored.time_context == source


def test_finish_sets_total_latency():
    ev = TurnEvent(started_at=100.0)
    ev.finish()
    assert ev.finished_at >= 100.0
    assert ev.total_latency_ms >= 0


# ---------------------------------------------------------------------------
# Serialización
# ---------------------------------------------------------------------------


def test_trace_round_trip_json():
    trace = TurnEvent(
        correlation_id="ab12",
        user_id="42",
        messages_in=[{"author": "David", "text": "hola"}],
        prompt_system="sistema",
        raw_llm='{"reply": "hola"}',
        parsed={"reply": "hola", "gif": "none"},
        disconnect={"leave": True, "reason": "me voy a dormir"},
        stay_active=False,
        shutdown_request={
            "origin": "model",
            "reason": "me voy a dormir",
            "correlation_id": "ab12",
            "requested_at": 123.0,
        },
        affinity_before=10,
        affinity_after=12,
        timings_ms={"llm_ms": 120},
    )
    data = trace.to_dict()
    assert data["correlation_id"] == "ab12"
    assert data["reproducible"] is True
    assert data["disconnect"]["leave"] is True
    assert data["stay_active"] is False
    assert data["shutdown_request"]["origin"] == "model"
    clone = TurnEvent.from_dict(json.loads(json.dumps(data)))
    assert clone == trace


def test_trace_serialization_redacts_web_query_and_content_but_keeps_status():
    trace = TurnEvent(
        correlation_id="private", web_query="consulta privada",
        search_query="consulta privada", web_context="snippet privado",
        web_requested=True, web_grounded=False,
    )

    data = trace.to_dict()

    assert "web_query" not in data
    assert "search_query" not in data
    assert "web_context" not in data
    assert data["web_requested"] is True
    assert data["web_grounded"] is False


def test_trace_serialization_redacts_private_fixture_text_and_keeps_presence():
    secret = "objetivo reservado"
    trace = TurnEvent(
        prompt_system=f"Contexto: {secret}", private_task_texts=[secret],
        task_context_available=True, task_context_schema="airi.task-context.v1",
    )

    data = trace.to_dict()

    assert secret not in json.dumps(data, ensure_ascii=False)
    assert data["task_context_available"] is True
    assert data["task_context_schema"] == "airi.task-context.v1"
    assert "private_task_texts" not in data


def test_kind_survives_round_trip():
    ev = TurnEvent(kind="gift", correlation_id="g1", raw_input="!regalo rosas")
    clone = TurnEvent.from_dict(ev.to_dict())
    assert clone.kind == "gift"
    assert clone.raw_input == "!regalo rosas"


def test_to_dict_omits_none_fields_but_keeps_raw_llm():
    data = TurnEvent(correlation_id="x").to_dict()
    assert "date_event" not in data  # None → eliminado
    assert data["raw_llm"] is None  # siempre presente
    assert data["reproducible"] is False


def test_trace_without_raw_is_not_reproducible():
    trace = TurnEvent(correlation_id="x", user_id="1")
    data = trace.to_dict(keep_raw=False)
    assert data["raw_llm"] is None
    assert data["reproducible"] is False


def test_trace_clips_huge_prompts():
    trace = TurnEvent(
        correlation_id="y", user_id="1", prompt_system="p" * 100_000,
        history_in=[{"role": "user", "content": "c" * 100_000}],
    )
    data = trace.to_dict()
    assert len(data["prompt_system"]) < 100_000
    assert "[truncado" in data["prompt_system"]
    assert "[truncado" in data["history_in"][0]["content"]


def test_raw_llm_clipped_but_replay_still_detects_it():
    trace = TurnEvent(correlation_id="big", user_id="1", raw_llm="r" * (MAX_RAW_LLM_CHARS + 100))
    data = trace.to_dict()
    assert "[truncado" in data["raw_llm"]
    assert data["reproducible"] is True


def test_trace_from_dict_ignores_unknown_keys():
    trace = TurnEvent.from_dict({"correlation_id": "z", "campo_futuro": 1})
    assert trace.correlation_id == "z"


# ---------------------------------------------------------------------------
# Rutas y guardado en disco (best-effort)
# ---------------------------------------------------------------------------


def test_trace_path_groups_by_day():
    path = trace_path("/tmp/traces", "ab12")
    assert path.startswith("/tmp/traces/")
    assert path.endswith("/ab12.json")
    assert len(path.split("/")) == 5  # <dir>/<YYYY-MM-DD>/<cid>.json


def test_trace_path_sanitizes_correlation_id():
    path = trace_path("/tmp/t", "../../etc/passwd")
    assert ".." not in path.split("/")[-1]


def test_save_trace_creates_file_and_returns_path(tmp_path):
    trace = TurnEvent(correlation_id="ab12", user_id="42", final_reply="hola")
    path = save_turn_trace(trace, str(tmp_path))
    assert path is not None
    loaded = load_turn_trace(path)
    assert loaded.reply == "hola"
    assert loaded.correlation_id == "ab12"


def test_save_trace_disabled_returns_none():
    assert save_turn_trace(TurnEvent(correlation_id="a"), "") is None


def test_save_trace_failure_returns_none(tmp_path):
    # Directorio convertido en fichero: makedirs falla → None, sin excepción.
    blocker = tmp_path / "bloqueado"
    blocker.write_text("x")
    trace = TurnEvent(correlation_id="cid", user_id="1")
    assert save_turn_trace(trace, str(blocker / "sub")) is None
