"""Tests unitarios del contrato y serializador de eventos JSONL.

Cubre el esquema versionado, los estados terminales de un modulo, el resumen
final y la proteccion de datos sensibles.
"""

from __future__ import annotations

import json

import pytest

from airi.observability import jsonl_events as jl

SCHEMA = "airi.log.v1"
LEVEL = "INFO"
INTERACTION_ID = "abc123"


def _line(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Construccion de lneas individuales
# ---------------------------------------------------------------------------


def test_build_start_contains_required_fields():
    line = jl.build_start(INTERACTION_ID)
    obj = json.loads(line)
    assert obj["schema"] == SCHEMA
    assert obj["level"] == LEVEL
    assert obj["interaction_id"] == INTERACTION_ID
    assert obj["event"] == jl.EVENT_START
    assert jl.now_iso() in obj["ts"]


def test_build_module_result_uses_terminal_states():
    line = jl.build_module_result(
        INTERACTION_ID, "conversation", "activated", duration_ms=12.5
    )
    obj = json.loads(line)
    assert obj["module"] == "conversation"
    assert obj["status"] == "activated"
    assert obj["reason_code"] is None
    assert obj["duration_ms"] == 12.5


@pytest.mark.parametrize("bad_status", ["pending", "unhandled", "ERROR"])
def test_build_module_result_rejects_unknown_status(bad_status):
    with pytest.raises(ValueError):
        jl.build_module_result(INTERACTION_ID, "conversation", bad_status)


def test_build_module_error_returns_failed_state():
    line = jl.build_module_error(
        INTERACTION_ID, "llm_call", "LLMError", "overloaded"
    )
    obj = json.loads(line)
    assert obj["status"] == "failed"
    assert obj["error_type"] == "LLMError"
    assert obj["error_message"] == "overloaded"


# ---------------------------------------------------------------------------
# Escritura de una sola linea JSON
# ---------------------------------------------------------------------------


def test_event_line_is_single_valid_json_object():
    line = jl.event_line(jl.EVENT_MODULE_RESULT, INTERACTION_ID, module="x", status="activated")
    assert line.startswith("{")
    assert line.rstrip().endswith("}")
    assert "\n" not in line
    json.loads(line)  # lanza si no es JSON valido


def test_event_line_has_normalized_ts_utc():
    line = jl.event_line(jl.EVENT_START, INTERACTION_ID)
    obj = json.loads(line)
    assert obj["ts"].endswith("Z")


# ---------------------------------------------------------------------------
# Resumen final por interaccion
# ---------------------------------------------------------------------------


def test_summary_lists_every_catalog_module_once():
    modules = {
        "conversation": jl.ModuleResult(status="activated", duration_ms=40.0),
        "llm_call": jl.ModuleResult(status="skipped", reason_code="not_requested", duration_ms=0.0),
    }
    line = jl.build_summary(INTERACTION_ID, modules, total_ms=120.0)
    obj = json.loads(line)
    assert obj["event"] == jl.EVENT_SUMMARY
    assert obj["total_ms"] == 120.0
    assert set(obj["modules"]) == set(modules)
    assert len(obj["modules"]) == len(modules)


def test_summary_contains_all_module_statuses():
    modules = {
        "conversation": jl.ModuleResult(status="activated"),
        "llm_call": jl.ModuleResult(status="skipped", reason_code="none"),
    }
    line = jl.build_summary(INTERACTION_ID, modules)
    obj = json.loads(line)
    assert obj["modules"]["conversation"]["status"] == "activated"
    assert obj["modules"]["llm_call"]["status"] == "skipped"
    assert obj["modules"]["llm_call"]["reason_code"] == "none"


# ---------------------------------------------------------------------------
# Proteccion de datos sensibles
# ---------------------------------------------------------------------------


def test_sanitize_removes_sensitive_keys():
    event = {
        "schema": SCHEMA,
        "interaction_id": INTERACTION_ID,
        "event": jl.EVENT_MODULE_RESULT,
        "module": "conversation",
        "status": "activated",
        "prompt": "no compartir",
        "content": "no usar",
        "secret_key": "x",
        "plain": "ok",
    }
    clean = jl.sanitize_event(event)
    assert "prompt" not in clean
    assert "content" not in clean
    assert "secret_key" not in clean
    assert clean["plain"] == "ok"
    assert clean["module"] == "conversation"


def test_sanitize_handles_nested_lists():
    payload = {"a": [{"content": "privado"}, {"ok": True}]}
    assert jl.sanitize_event(payload) == {"a": [{}, {"ok": True}]}


# ---------------------------------------------------------------------------
# Rondas de traza JSONL
# ---------------------------------------------------------------------------


def test_jsonl_logger_round_trip():
    logger = jl.JsonlInteractionLogger(INTERACTION_ID, catalog=["conversation", "llm_call"])
    first = logger.start()
    second = logger.module_result("conversation", "activated", duration_ms=40.0)
    third = logger.summary(duration_ms=120.0)
    assert json.loads(first)["event"] == jl.EVENT_START
    assert json.loads(second)["module"] == "conversation"
    assert json.loads(third)["event"] == jl.EVENT_SUMMARY
    third_obj = json.loads(third)
    assert third_obj["event"] == jl.EVENT_SUMMARY
    assert set(third_obj["modules"]) == {"conversation", "llm_call"}
    assert third_obj["modules"]["conversation"]["status"] == "activated"
    assert third_obj["modules"]["llm_call"]["status"] == "skipped"
    assert third_obj["modules"]["llm_call"]["reason_code"] == "not_requested"


# ---------------------------------------------------------------------------
# Cumplimiento del ciclo de vida y del catalago completo
# ---------------------------------------------------------------------------


def test_summary_fills_every_catalog_module_when_not_recorded():
    logger = jl.JsonlInteractionLogger(
        'corr-1', catalog=['conversation', 'llm_call', 'publication']
    )
    logger.module_result('conversation', 'activated', duration_ms=40.0)

    line = logger.summary(duration_ms=120.0)
    obj = json.loads(line)

    assert obj['event'] == jl.EVENT_SUMMARY
    assert obj['total_ms'] == 120.0
    assert set(obj['modules']) == {'conversation', 'llm_call', 'publication'}
    assert obj['modules']['conversation']['status'] == 'activated'
    assert obj['modules']['llm_call']['status'] == 'skipped'
    assert obj['modules']['llm_call']['reason_code'] == 'not_requested'
    assert obj['modules']['publication']['status'] == 'skipped'


def test_correlation_id_is_preserved_across_the_jsonl_stream():
    cid = 'corr-9f2a'
    logger = jl.JsonlInteractionLogger(cid, catalog=['conversation'])

    logger.start()
    logger.module_result('conversation', 'activated', duration_ms=25.0)
    last = logger.summary(duration_ms=80.0)

    for line in (logger.start(), logger.module_result('conversation', 'activated'), last):
        assert json.loads(line)['interaction_id'] == cid
