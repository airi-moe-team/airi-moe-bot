import asyncio

from airi.evaluation.interaction import (
    TEMPORAL_SCENARIOS,
    detect_clock_recital,
)
from airi.testing import FakeLLM, llm_json


def test_temporal_scenarios_cover_dayparts_gaps_and_proactive():
    assert len(TEMPORAL_SCENARIOS) == 7
    ids = {scenario.id for scenario in TEMPORAL_SCENARIOS}
    assert {"madrugada", "mañana", "tarde", "noche"} <= ids
    assert "reaparicion_tres_dias" in ids
    assert "proactivo_nocturno" in ids
    assert next(s for s in TEMPORAL_SCENARIOS if s.id == "dos_minutos").last_seen_seconds == 120


def test_clock_recital_detector_uses_fixed_time_and_flags_clock_claims():
    context = {"local_iso": "2026-10-27T03:14"}
    assert detect_clock_recital("Son las 03:14, qué tarde.", context) is True
    assert detect_clock_recital("Según mi reloj ya es tarde.", context) is True
    assert detect_clock_recital("Qué noche tan tranquila.", context) is False
    assert detect_clock_recital("No hay hora disponible.", {}) is None


def test_live_temporal_evaluation_supports_ab_at_same_fixed_instant():
    from airi.evaluation.interaction import generate_live_records

    scenario = (TEMPORAL_SCENARIOS[4],)
    baseline = asyncio.run(generate_live_records(
        llm=FakeLLM(default_reply=llm_json("¡Qué pronto vuelves!")),
        scenarios=scenario,
        time_context_enabled=False,
    ))
    candidate = asyncio.run(generate_live_records(
        llm=FakeLLM(default_reply=llm_json("Me alegra que volvieras.")),
        scenarios=scenario,
        time_context_enabled=True,
    ))
    assert baseline[0]["time_evaluation_status"] == "not_evaluable"
    assert candidate[0]["time_evaluation_status"] == "evaluated"
    assert candidate[0]["clock_recital"] is False
    assert "=== TU PERCEPCIÓN DEL TIEMPO ===" in candidate[0]["prompt_system"]
    assert "=== TU PERCEPCIÓN DEL TIEMPO ===" not in baseline[0]["prompt_system"]


def test_proactive_night_scenario_records_mode_and_daypart_instruction():
    from airi.evaluation.interaction import generate_live_records

    records = asyncio.run(generate_live_records(
        llm=FakeLLM(default_reply=llm_json("Se me ocurrió algo para contar.")),
        scenarios=(TEMPORAL_SCENARIOS[-1],),
        time_context_enabled=True,
    ))
    assert records[0]["conversation_mode"] == "proactive"
    assert "no propongas planes propios de otra franja" in records[0]["prompt_system"]
