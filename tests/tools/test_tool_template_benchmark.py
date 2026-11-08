"""Tests del benchmark A/B de tool-template (sin red)."""

from __future__ import annotations

import json

import pytest
import tools.tool_template_benchmark as bench


def _record(**overrides):
    payload = {
        "scenario": "bench_saludo",
        "reply": "hola",
        "parse_ok": True,
        "finish_reason": "stop",
        "total_latency_ms": 1200,
        "llm_usage": {
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "total_tokens": 140,
        },
        "llm_calls": [{
            "ttft_ms": 300,
            "first_content_ms": 900,
            "reasoning_tokens": 20,
            "reasoning_chars": 80,
            "declared_tools": 1,
            "synthetic_tool_call_ignored": None,
            "tool_calls_present": False,
        }],
    }
    payload.update(overrides)
    return payload


def test_summarize_counts_visible_parse_and_truncation():
    records = [
        _record(),
        _record(reply="", parse_ok=False, finish_reason="length"),
    ]

    summary = bench.summarize_records(records, enabled=True)

    assert summary["turns"] == 2
    assert summary["visible_replies"] == 1
    assert summary["empty_replies"] == 1
    assert summary["parse_failures"] == 1
    assert summary["truncated_finish_length"] == 1
    assert summary["tool_template_optimization"] is True


def test_summarize_reports_synthetic_tool_anomalies():
    records = [
        _record(llm_calls=[{
            "synthetic_tool_call_ignored": True,
            "tool_calls_present": True,
            "reasoning_chars": 10,
        }])
    ]

    summary = bench.summarize_records(records, enabled=True)

    assert summary["tool_call_anomalies_ignored"] == 1
    assert summary["tool_calls_present"] == 1


def test_build_report_keeps_text_out_and_flags_review():
    report = bench.build_report(
        [_record()],
        [_record(total_latency_ms=900)],
    )

    serialized = json.dumps(report)

    assert "hola" not in serialized
    assert report["candidate_minus_baseline"]["turn_latency_ms_median"] == -300
    assert report["quality_review_required"] is True
    assert report["experimental"] is True


def test_cli_requires_live_and_minimum_repeats():
    with pytest.raises(SystemExit):
        bench.main([])
    with pytest.raises(SystemExit):
        bench.main(["--live", "--repeat", "4"])
    with pytest.raises(SystemExit):
        bench.main(["--live", "--pilot", "--repeat", "0"])


def test_select_scenarios_defaults_to_all_and_filters_by_id():
    assert bench.select_scenarios(None) == bench.BENCHMARK_SCENARIOS
    assert bench.select_scenarios([]) == bench.BENCHMARK_SCENARIOS

    chosen = bench.select_scenarios(["bench_saludo", "bench_multiusuario"])

    assert [scenario.id for scenario in chosen] == [
        "bench_saludo",
        "bench_multiusuario",
    ]


def test_select_scenarios_rejects_unknown_ids():
    with pytest.raises(ValueError, match="desconocido"):
        bench.select_scenarios(["bench_saludo", "no_existe"])


def test_resolve_repeat_requires_five_outside_pilot():
    assert bench.resolve_repeat(None, pilot=False) == bench.MIN_REPEATS
    assert bench.resolve_repeat(5, pilot=False) == 5
    with pytest.raises(ValueError, match="pilot"):
        bench.resolve_repeat(4, pilot=False)

    assert bench.resolve_repeat(None, pilot=True) == bench.PILOT_REPEATS
    assert bench.resolve_repeat(2, pilot=True) == 2
    with pytest.raises(ValueError):
        bench.resolve_repeat(0, pilot=True)


def test_record_sink_persists_each_record_as_it_arrives(tmp_path):
    path = tmp_path / "records.jsonl"
    sink = bench.RecordSink(path)

    sink(_record())
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    sink(_record(reply="segunda"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["reply"] == "segunda"
    assert len(sink.records) == 2

    sink.close()


def test_record_sink_without_path_keeps_records_only():
    sink = bench.RecordSink(None)

    sink(_record())

    assert len(sink.records) == 1
    sink.close()


def test_benchmark_rejects_on_label_when_primary_not_optimized():
    record = _record(llm_calls=[{
        "purpose": "primary", "tool_template_optimization": False,
        "declared_tools": None,
    }])
    with pytest.raises(ValueError, match="principal"):
        bench.verify_primary_application(record, enabled=True)


def test_benchmark_accepts_only_matching_primary_metadata():
    for enabled, count in ((False, None), (True, 1)):
        record = _record(llm_calls=[
            {"purpose": "web_search_decision", "tool_template_optimization": False},
            {"purpose": "primary", "tool_template_optimization": enabled,
             "declared_tools": count},
        ])
        bench.verify_primary_application(record, enabled=enabled)
    with pytest.raises(ValueError, match="principal"):
        bench.verify_primary_application(_record(llm_calls=[]), enabled=True)


def test_benchmark_baseline_disables_only_trial_client():
    class Client:
        def _tool_template_active(self, **kwargs):
            return True

    baseline, candidate = Client(), Client()
    bench.disable_tool_template_for_baseline(baseline)

    assert baseline._tool_template_active(schema={}, strict_schema=True,
                                           tools=None, tool_choice=None) is False
    assert candidate._tool_template_active(schema={}, strict_schema=True,
                                            tools=None, tool_choice=None) is True


def test_benchmark_does_not_persist_mislabeled_on_record(tmp_path):
    path = tmp_path / "records.jsonl"
    sink = bench.RecordSink(path)
    record = _record(llm_calls=[{
        "purpose": "primary", "tool_template_optimization": False,
        "declared_tools": None,
    }])

    with pytest.raises(ValueError, match="principal"):
        bench.save_verified_record(record, enabled=True, sink=sink)

    assert sink.records == []
    assert path.read_text(encoding="utf-8") == ""
    sink.close()
