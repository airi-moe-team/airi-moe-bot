"""Tests del corpus/rúbrica local de barrido de razonamiento."""

import asyncio

from airi.observability.reasoning_sweep import (
    HUMAN_REVIEW_DIMENSIONS,
    SCENARIOS,
    build_history,
    build_report,
    evaluate_reply,
    review_samples_blind,
    run_sweep,
)
from airi.testing import FakeLLM, llm_json


def test_corpus_covers_memory_correction_constraints_topic_return_and_multifact():
    keys = {scenario.key for scenario in SCENARIOS}
    assert keys == {
        "old_preference",
        "latest_correction",
        "project_constraints",
        "topic_return",
        "two_facts",
    }


def test_depth_adds_distractors_without_dropping_anchor_turns():
    scenario = next(s for s in SCENARIOS if s.key == "old_preference")
    short = build_history(scenario, 0)
    long = build_history(scenario, 8)

    assert len(long) == len(short) + 8
    assert any("jazmín" in message["content"] for message in long)


def test_lexical_rubric_detects_missing_and_forbidden_anchors():
    scenario = next(s for s in SCENARIOS if s.key == "latest_correction")

    assert evaluate_reply(scenario, "Quedó confirmado el jueves.")["passed_anchors"]
    failed = evaluate_reply(scenario, "Quedó para el martes.")
    assert failed["passed_anchors"] is False
    assert failed["missing_anchor_groups"] == [["jueves"]]
    assert failed["forbidden_terms_found"] == ["martes"]


def test_two_fact_rubric_flags_wrong_extra_meeting_time():
    scenario = next(s for s in SCENARIOS if s.key == "two_facts")

    result = evaluate_reply(
        scenario,
        "Llegas a las seis veinte y nos vemos en el Café Azul a las seis y cuarto.",
    )

    assert result["passed_anchors"] is False
    assert result["forbidden_terms_found"] == ["seis y cuarto"]


def test_project_constraints_accepts_paraphrases_without_unasked_engine_name():
    scenario = next(s for s in SCENARIOS if s.key == "project_constraints")

    result = evaluate_reply(
        scenario,
        "La exploración debería sentirse segura y sin tensión constante.",
    )

    assert result["passed_anchors"] is True


def test_sweet_spot_is_lowest_budget_passing_each_context_depth():
    rows = []
    for budget, scores in ((512, (1.0, 0.5)), (1024, (1.0, 1.0)), (2048, (1.0, 1.0))):
        for depth, score in zip((0, 20), scores, strict=True):
            for passed in (True,) * int(score * 2) + (False,) * (2 - int(score * 2)):
                rows.append({
                    "budget": budget,
                    "depth": depth,
                    "quality": {"passed_anchors": passed},
                    "latency_ms": 100 + budget,
                    "prompt_tokens": 1000,
                    "completion_tokens": 50,
                    "reasoning_tokens": None,
                    "finish_reason": "stop",
                    "human_review": {
                        "ratings": dict.fromkeys(HUMAN_REVIEW_DIMENSIONS, 4),
                        "passed": passed,
                    },
                })

    report = build_report(rows, min_pass_rate=0.9)

    assert report["candidate_sweet_spot_tokens"] == 1024


def test_report_does_not_recommend_budget_before_human_review():
    row = {
        "budget": 512,
        "depth": 0,
        "quality": {"passed_anchors": True},
        "latency_ms": 100,
        "prompt_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,
        "finish_reason": "stop",
    }

    report = build_report([row], min_pass_rate=0.9)

    assert report["anchor_only_candidate_tokens"] == 512
    assert report["candidate_sweet_spot_tokens"] is None
    assert report["decision_status"] == "requires_blind_human_review"


def test_report_requires_human_review_to_pass_at_each_context_depth():
    rows = []
    for depth, human_passed in ((0, True), (20, False)):
        rows.append({
            "budget": 512,
            "depth": depth,
            "quality": {"passed_anchors": True},
            "latency_ms": 100,
            "prompt_tokens": None,
            "completion_tokens": None,
            "reasoning_tokens": None,
            "finish_reason": "stop",
            "human_review": {
                "ratings": dict.fromkeys(HUMAN_REVIEW_DIMENSIONS, 4),
                "passed": human_passed,
            },
        })

    report = build_report(rows, min_pass_rate=0.9)

    assert report["candidate_sweet_spot_tokens"] is None
    assert report["decision_status"] == "no_budget_passed"


def test_blind_review_shuffles_and_saves_five_dimension_scores():
    samples = [{
        "scenario_label": "Prueba",
        "depth": 0,
        "answer": "Respuesta sintética",
        "budget": 512,
        "quality": {"passed_anchors": True},
    }]
    prompts = []
    shown = []

    review_samples_blind(
        samples,
        input_fn=lambda prompt: prompts.append(prompt) or "4",
        output_fn=shown.append,
        shuffle_fn=lambda rows: None,
    )

    assert len(prompts) == len(HUMAN_REVIEW_DIMENSIONS)
    assert all("512" not in text for text in shown)
    assert samples[0]["human_review"]["ratings"] == dict.fromkeys(
        HUMAN_REVIEW_DIMENSIONS, 4
    )
    assert samples[0]["human_review"]["passed"] is True


def test_sweep_calls_checkpoint_after_each_completed_sample():
    llm = FakeLLM(replies=[llm_json("La preferencia es el té de jazmín.")])
    llm.provider = "llama"
    llm.thinking_mode = "auto"
    checkpoints = []

    rows = asyncio.run(run_sweep(
        llm,
        budgets=(1024,),
        depths=(0,),
        repeats=1,
        scenario_keys=("old_preference",),
        on_sample=checkpoints.append,
    ))

    assert len(rows) == len(checkpoints) == 1
    assert checkpoints[0]["effective_reasoning_budget_tokens"] == 1024
