"""Tests de las métricas narrativas y de los escenarios de evaluación."""

from __future__ import annotations

from airi.evaluation.narrative import (
    NON_ROMANTIC_CATEGORIES,
    SCENARIOS,
    compare_runs,
    evaluate_records,
)


def record(**overrides):
    payload = {
        "scenario": "neutral_saludo",
        "category": "neutral",
        "turn": 1,
        "user": "hola",
        "reply": "Hola~ ¿qué tal?",
        "romantic_question": False,
        "stage_before": "none",
        "stage_after": "none",
        "romantic_update": None,
        "evidence_refs": [],
        "partner_confirmed": False,
        "proposal_pending": False,
    }
    payload.update(overrides)
    return payload


def test_clean_run_passes_with_zero_violations():
    metrics = evaluate_records([record(), record(turn=2)])
    assert metrics.passed is True
    assert metrics.violations == 0
    assert metrics.turns == 2


def test_unsolicited_romantic_questions_are_counted():
    metrics = evaluate_records([
        record(romantic_question=True),
        record(category="factual", romantic_question=True),
        record(category="proposal_accepted", romantic_question=True),
    ])
    assert metrics.unsolicited_romantic_questions == 2


def test_a_romantic_question_written_in_the_reply_is_counted():
    metrics = evaluate_records([
        record(category="neutral", reply="¿Quieres ser mi pareja?"),
    ])
    assert metrics.unsolicited_romantic_questions == 1
    assert metrics.passed is False


def test_an_ordinary_question_in_the_reply_is_not_romantic():
    metrics = evaluate_records([
        record(category="neutral", reply="¿Qué tal tu día?"),
    ])
    assert metrics.unsolicited_romantic_questions == 0
    assert metrics.passed is True


def test_transitions_without_evidence_are_counted():
    metrics = evaluate_records([
        record(
            stage_before="none",
            stage_after="curiosity",
            romantic_update="curiosity",
            evidence_refs=[],
        )
    ])
    assert metrics.transitions_without_evidence == 1


def test_premature_partner_and_enamored_claims_are_counted():
    metrics = evaluate_records([
        record(reply="Ya somos pareja.", partner_confirmed=False),
        record(reply="Me he enamorado de ti.", stage_after="interest"),
    ])
    assert metrics.premature_partner_claims == 1
    assert metrics.unconfirmed_enamored_claims == 1


def test_stage_contradiction_uses_the_annotated_claim():
    metrics = evaluate_records([
        record(stage_after="interest", claimed_stage="enamored")
    ])
    assert metrics.stage_contradictions == 1


def test_scenarios_cover_all_required_situations():
    categories = {scenario.category for scenario in SCENARIOS}
    required = {
        "neutral",
        "factual",
        "generic_praise",
        "love_instruction",
        "support",
        "remembered_detail",
        "reconciliation",
        "date_without_question",
        "proposal_accepted",
        "proposal_rejected",
        "proposal_ambiguous",
        "continuity",
    }
    assert required <= categories
    assert NON_ROMANTIC_CATEGORIES <= categories


def test_scenarios_are_multi_turn_and_unique():
    ids = [scenario.id for scenario in SCENARIOS]
    assert len(ids) == len(set(ids))
    assert all(scenario.turns for scenario in SCENARIOS)
    assert sum(1 for s in SCENARIOS if len(s.turns) > 1) >= 5


def test_compare_runs_reports_regressions():
    baseline = [record()]
    candidate = [record(romantic_question=True)]
    result = compare_runs(baseline, candidate)
    assert result["regression"] is True
    assert result["delta"]["unsolicited_romantic_questions"] == 1
    assert result["candidate"]["passed"] is False


def test_runner_produces_evaluable_records_with_a_fake_llm():
    import asyncio

    from airi.evaluation.narrative import Scenario
    from airi.evaluation.runner import run_scenario
    from airi.services.conversation import ConversationService
    from airi.testing import FakeLLM, FakeUser, llm_json, make_state

    scenario = Scenario("neutral_test", "neutral", "charla", ("hola", "¿qué tal?"))
    state, _ = make_state(now=100.0)
    service = ConversationService(
        llm=FakeLLM([llm_json("Hola~"), llm_json("Bien, gracias~")]),
        state=state,
        clock=lambda: 100.0,
    )
    records = asyncio.run(
        run_scenario(scenario, service, FakeUser(1, "Ana"), now=100.0)
    )
    assert len(records) == 2
    assert records[0]["scenario"] == "neutral_test"
    assert evaluate_records(records).passed is True
