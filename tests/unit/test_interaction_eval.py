"""Tests de los escenarios, métricas y runner live de interacción natural."""

from __future__ import annotations

import asyncio

from airi.evaluation.interaction import (
    INTERACTION_SCENARIOS,
    RUBRIC_CRITERIA,
    RUBRIC_MAX_TOTAL,
    compare_interactions,
    evaluate_interactions,
    generate_live_records,
)


def record(**overrides):
    payload = {
        "scenario": "pregunta_directa",
        "category": "direct_question",
        "turn": 1,
        "user": "¿café o té?",
        "reply": "Prefiero el té.",
        "parse_ok": True,
        "finish_reason": "stop",
        "disconnect": None,
        "stay_active": True,
        "conversation_mode": "normal",
    }
    payload.update(overrides)
    return payload


def test_scenarios_cover_the_seven_required_situations():
    ids = [scenario.id for scenario in INTERACTION_SCENARIOS]
    categories = {scenario.category for scenario in INTERACTION_SCENARIOS}
    assert len(ids) == 7
    assert len(ids) == len(set(ids))
    assert {
        "direct_question",
        "correction",
        "brief_greeting",
        "corrected_preference",
        "disagreement",
        "casual",
        "farewell",
    } <= categories
    assert all(scenario.turns for scenario in INTERACTION_SCENARIOS)
    assert sum(1 for scenario in INTERACTION_SCENARIOS if len(scenario.turns) > 1) >= 5


def test_question_only_replies_and_repeated_closings_are_counted():
    metrics = evaluate_interactions(
        [
            record(scenario="a", turn=1, reply="¿Y tú?"),
            record(scenario="a", turn=2, reply="Bien. ¿Y tú?"),
            record(scenario="b", turn=1, reply="Claro. ¿Y tú?"),
        ]
    )
    assert metrics.question_only_replies == 1
    assert metrics.repeated_closings == 1
    assert metrics.quality_violations == 2


def test_stacked_gestures_and_density_are_measured():
    metrics = evaluate_interactions(
        [
            record(reply="*sonríe* Me gusta el té. *se encoge de hombros*"),
            record(turn=2, reply="Y a ti también."),
        ]
    )
    assert metrics.stacked_gestures == 1
    assert metrics.gesture_density == 1.0


def test_prefab_farewells_and_disproportionate_replies_are_counted():
    metrics = evaluate_interactions(
        [
            record(reply="Aquí estaré, sueños dulces."),
            record(
                turn=2,
                user="hola",
                reply="palabra " * 80,
            ),
        ]
    )
    assert metrics.prefab_farewells == 1
    assert metrics.disproportionate_replies == 1


def test_prefab_detection_covers_availability_promises():
    metrics = evaluate_interactions(
        [
            record(reply="Estoy aquí para acompañarte."),
            record(turn=2, reply="Me apunto a estar aquí esperándote."),
            record(turn=3, reply="Cuenta conmigo para lo que necesites."),
        ]
    )
    assert metrics.prefab_farewells == 3


def test_schema_and_state_failures_are_critical():
    metrics = evaluate_interactions(
        [
            record(parse_ok=False),
            record(finish_reason="length"),
            record(reply="Me voy a dormir.", disconnect={"leave": False}),
            record(reply="Qué tengas buena noche.", disconnect={"leave": True}),
        ]
    )
    assert metrics.schema_failures == 1
    assert metrics.truncated_replies == 1
    assert metrics.state_contradictions == 2
    assert metrics.critical_violations == 4
    assert metrics.passed is False


def test_rubric_is_per_scenario_and_caps_at_seventy():
    records = []
    for index, scenario in enumerate(INTERACTION_SCENARIOS):
        rubric = {criterion: 2 for criterion in RUBRIC_CRITERIA}
        records.append(record(scenario=scenario.id, turn=1, rubric=rubric))
        # Anotar el mismo escenario otra vez no duplica la puntuación.
        records.append(record(scenario=scenario.id, turn=2, rubric=rubric))
    metrics = evaluate_interactions(records)
    assert metrics.rubric_scenarios_scored == 7
    assert metrics.rubric_total == RUBRIC_MAX_TOTAL


def test_compare_marks_only_critical_regressions_as_failure():
    baseline = [record()]
    candidate = [record(parse_ok=False)]
    result = compare_interactions(baseline, candidate)
    assert result["regression"] is True
    assert result["critical_regression"] is True
    assert result["delta"]["schema_failures"] == 1

    quality_only = [record(reply="¿Y tú?")]
    result = compare_interactions(baseline, quality_only)
    assert result["regression"] is False
    assert result["quality_regression"] is True


def test_live_generation_uses_a_fake_llm_without_network():
    from airi.testing import FakeLLM, llm_json

    records = asyncio.run(
        generate_live_records(
            llm=FakeLLM(default_reply=llm_json("Prefiero el té.")),
            repeat=1,
        )
    )
    assert len(records) == sum(len(s.turns) for s in INTERACTION_SCENARIOS)
    assert {r["scenario"] for r in records} == {
        s.id for s in INTERACTION_SCENARIOS
    }
    assert all(r["prompt_sha256"] for r in records)
    assert all(r["model"] for r in records)
    assert all(r["parse_ok"] is True for r in records)


def test_memory_snapshots_are_not_mutated_by_later_turns():
    from airi.evaluation.interaction import InteractionScenario
    from airi.testing import FakeLLM, llm_json

    scenario = InteractionScenario(
        "memoria",
        "corrected_preference",
        "corrección",
        (
            "Mi postre favorito es el flan.",
            "No, me equivoqué: mi postre favorito es el tiramisú.",
        ),
        seed_memories=("Le encanta el flan.",),
    )
    llm = FakeLLM(
        replies=[
            llm_json("Un flan.", memory="Le encanta el flan."),
            llm_json("Entendido."),
        ]
    )
    records = asyncio.run(
        generate_live_records(llm=llm, scenarios=(scenario,))
    )
    assert records[0]["memories_after"][0]["status"] == "active"
    assert records[1]["memories_after"][0]["status"] == "superseded"
    assert [
        item["text"]
        for item in records[1]["memories_after"]
        if item["status"] == "active"
    ] == ["Su postre favorito es el tiramisú."]
