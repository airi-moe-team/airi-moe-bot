import json

from airi.domain.prompts import WEB_SEARCH_DECISION_PROMPT
from airi.evaluation.web_search import (
    WEB_SEARCH_SCENARIOS,
    append_web_search_records,
    evaluate_web_search_records,
    parse_semantic_judgment,
)


def test_web_search_eval_defines_the_eight_expected_scenarios():
    assert len(WEB_SEARCH_SCENARIOS) == 8
    assert {scenario.id for scenario in WEB_SEARCH_SCENARIOS} == {
        "curiosity",
        "memory_uncertainty",
        "factual_debate",
        "contradictory_notes",
        "explicit_request",
        "opinion_no_search",
        "empty_search",
        "web_disabled_mode",
    }


def test_decision_policy_allows_initiative_for_open_factual_curiosity():
    assert "curiosidad factual abierta" in WEB_SEARCH_DECISION_PROMPT
    assert "algo reciente" in WEB_SEARCH_DECISION_PROMPT


def test_evaluation_reports_search_decision_precision_recall_and_case_results():
    report = evaluate_web_search_records([
        {"scenario": "curiosity", "expected_search": True, "actual_search": True},
        {"scenario": "debate", "expected_search": True, "actual_search": False},
        {"scenario": "opinion", "expected_search": False, "actual_search": True},
        {"scenario": "mode", "expected_search": False, "actual_search": False},
    ])

    assert report["decision_accuracy"] == 0.5
    assert report["precision"] == 0.5
    assert report["recall"] == 0.5
    assert report["true_positive"] == 1
    assert report["false_positive"] == 1
    assert report["false_negative"] == 1
    assert report["cases"][1]["decision"] == "missed_search"


def test_semantic_judgment_parser_accepts_json_and_rejects_non_object():
    parsed = parse_semantic_judgment(
        '{"query_resolved":"yes","motivation_integrated":"yes",'
        '"personal_reaction":"yes","report_style":"no",'
        '"uncertainty_calibrated":"not_applicable",'
        '"unsupported_specific_claim":"no","canned_phrase":"no",'
        '"rationale":"Natural y contextual."}'
    )

    assert parsed["query_resolved"] == "yes"
    assert parsed["report_style"] == "no"
    assert parsed["rationale"] == "Natural y contextual."
    assert parse_semantic_judgment("NO_JSON") is None


def test_semantic_parser_normalizes_boolean_labels():
    parsed = parse_semantic_judgment(
        json.dumps({
            "query_resolved": True,
            "motivation_integrated": True,
            "personal_reaction": True,
            "report_style": False,
            "uncertainty_calibrated": "not_applicable",
            "unsupported_specific_claim": False,
            "canned_phrase": False,
        })
    )
    assert parsed["query_resolved"] == "yes"
    assert parsed["report_style"] == "no"


def test_evaluation_includes_semantic_score_only_when_judge_result_exists():
    report = evaluate_web_search_records([
        {
            "scenario": "contradictory_notes",
            "expected_search": True,
            "actual_search": True,
            "semantic_judgment": {
                "query_resolved": "yes",
                "motivation_integrated": "yes",
                "personal_reaction": "yes",
                "report_style": "no",
                "uncertainty_calibrated": "yes",
                "unsupported_specific_claim": "no",
                "canned_phrase": "no",
            },
        }
    ])
    assert report["semantic_cases_scored"] == 1
    assert report["semantic_score"] == 7


def test_all_not_applicable_judgments_do_not_count_as_scored():
    report = evaluate_web_search_records([{
        "scenario": "incomplete-judge",
        "expected_search": True,
        "actual_search": True,
        "semantic_judgment": {
            **{key: "not_applicable" for key in (
                "query_resolved", "motivation_integrated", "personal_reaction",
                "report_style", "uncertainty_calibrated",
                "unsupported_specific_claim", "canned_phrase",
            )},
            "rationale": "El juez no completó las etiquetas.",
        },
    }])
    assert report["semantic_cases_scored"] == 0
    assert report["semantic_opportunities"] == 0


def test_completed_records_append_incrementally_as_jsonl(tmp_path):
    path = tmp_path / "eval" / "web.jsonl"
    append_web_search_records(path, [{"scenario": "one"}])
    append_web_search_records(path, [{"scenario": "two"}])

    assert [json.loads(line)["scenario"] for line in path.read_text().splitlines()] == [
        "one", "two",
    ]
