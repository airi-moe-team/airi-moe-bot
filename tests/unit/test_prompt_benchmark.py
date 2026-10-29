"""Pruebas del benchmark del prompt sin llamadas de red."""

import asyncio
import json

import pytest

from airi.observability.events import TurnEvent
from airi.observability.prometheus_metrics import parse_prometheus_text
from airi.observability.prompt_benchmark import (
    build_benchmark_report,
    run_prompt_benchmark,
)
from airi.ports.llm import LLMMeta
from airi.testing import FakeLLM, llm_json


def run(coro):
    return asyncio.run(coro)


def make_trace(path, *, kind="normal"):
    private_message = (
        "mensaje privado que no debe aparecer en el reporte y supera el umbral del turno breve"
    )
    event = TurnEvent(
        correlation_id="benchmark-trace",
        kind=kind,
        started_at=1_000_000.0,
        user_id="42",
        user_name="Persona privada",
        raw_input=private_message,
        messages_in=[{"text": private_message}],
        history_in=[{"role": "user", "content": "turno anterior"}],
        state_snapshot_affinity={"points": 10, "level": "Conocida"},
    )
    path.write_text(event.to_json(), encoding="utf-8")
    return event


def make_llm(
    *, calls=10, usage=None, finish_reason="stop", thinking_mode="on", include_timings=True
):
    meta_usage = usage if usage is not None else {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }
    llm = FakeLLM(replies=[llm_json("Respuesta privada") for _ in range(calls)], metas=[])
    llm.thinking_mode = thinking_mode
    llm.metas = [
        LLMMeta(
            finish_reason=finish_reason,
            usage=meta_usage,
            ttft_ms=35 if include_timings else None,
            first_content_ms=60 if include_timings else None,
            server_timings=(
                {"prompt_ms": 11.5, "predicted_ms": 20.0}
                if include_timings
                else None
            ),
            reasoning_present=True if include_timings else None,
            reasoning_tokens=4 if include_timings else None,
        )
        for _ in range(calls)
    ]
    return llm


def test_benchmark_rejects_less_than_five_pairs_before_inference(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace)
    llm = make_llm()

    with pytest.raises(ValueError, match="cinco"):
        run(run_prompt_benchmark(trace, llm, pair_count=4))

    assert llm.calls == []


def test_benchmark_requires_effective_thinking_on(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace)
    llm = make_llm(thinking_mode="auto")

    with pytest.raises(ValueError, match="thinking.*on"):
        run(run_prompt_benchmark(trace, llm))

    assert llm.calls == []


def test_generation_profile_can_set_low_effort_and_output_limit(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace)
    llm = make_llm(thinking_mode="low")

    samples = run(run_prompt_benchmark(
        trace,
        llm,
        pair_count=5,
        thinking_mode="low",
        max_output_tokens=512,
    ))

    assert len(samples) == 10
    assert all(sample.thinking_mode == "low" for sample in samples)
    assert all(sample.max_output_tokens == 512 for sample in samples)
    assert all(sample.calls[0]["reasoning_budget_tokens"] == 256 for sample in samples)
    assert all(call["max_tokens"] == 512 for call in llm.calls)


def test_generation_profile_rejects_nonpositive_output_limit_before_inference(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace)
    llm = make_llm()

    with pytest.raises(ValueError, match="positivo"):
        run(run_prompt_benchmark(trace, llm, max_output_tokens=0))

    assert llm.calls == []


def test_benchmark_runs_five_clean_alternating_pairs_and_omits_private_text(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace)
    llm = make_llm()
    reviews = []
    metric_reads = 0

    async def metrics_reader():
        nonlocal metric_reads
        metric_reads += 1
        return parse_prometheus_text(
            "# TYPE llama_requests_total counter\n"
            f"llama_requests_total {metric_reads}\n"
        )

    def reviewer(user_text, reply, variant):
        reviews.append((user_text, reply, variant))
        return {
            "relevant": True,
            "coherent": True,
            "proportional": True,
            "essential_rules": True,
        }

    samples = run(
        run_prompt_benchmark(
            trace, llm, quality_reviewer=reviewer, metrics_reader=metrics_reader
        )
    )
    report = build_benchmark_report(samples)

    assert len(samples) == 10
    assert [(sample.pair_index, sample.variant) for sample in samples] == [
        (pair, variant)
        for pair in range(1, 6)
        for variant in (("current", "compact_candidate") if pair % 2 else
                        ("compact_candidate", "current"))
    ]
    assert len(reviews) == 10
    assert all(sample.quality_acceptable for sample in samples)
    assert all(sample.ttft_ms == 35 for sample in samples)
    assert all(sample.first_content_ms == 60 for sample in samples)
    assert all(sample.server_timings["prompt_ms"] == 11.5 for sample in samples)
    assert all(sample.reasoning_tokens == 4 for sample in samples)
    assert all(sample.prometheus_status == "ok" for sample in samples)
    assert all(sample.prometheus_deltas[0]["delta"] == 1 for sample in samples)
    assert report["complete_pairs"] == 5
    assert report["candidate_acceptable"] is True
    assert report["prometheus_scope"] == "aggregate_snapshot_delta"
    assert report["server_timings"]["current"]["prompt_ms"]["median"] == 11.5
    assert report["variants"]["current"]["prompt_tokens"]["median"] == 100

    serialized = json.dumps(report, ensure_ascii=False)
    assert "mensaje privado" not in serialized
    assert "Respuesta privada" not in serialized
    for pair in range(5):
        first = llm.calls[pair * 2]
        second = llm.calls[pair * 2 + 1]
        assert first["messages"][1:] == second["messages"][1:]
        for key in ("schema", "max_tokens", "reasoning_budget_tokens", "quick_turn", "strict_schema"):
            assert first[key] == second[key]
        assert first["quick_turn"] is False
        assert first["stream"] is True


def test_benchmark_preserves_session_schema_for_active_trace(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace, kind="active")
    llm = make_llm()

    run(run_prompt_benchmark(trace, llm))

    assert all(
        "stay_active" in call["schema"]["properties"]
        for call in llm.calls
    )


def test_quality_pending_does_not_accept_candidate(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace)
    samples = run(run_prompt_benchmark(trace, make_llm()))
    report = build_benchmark_report(samples)

    assert report["candidate_acceptable"] is None
    assert all(sample.quality_review_pending for sample in samples)


def test_absent_usage_and_ttft_remain_null(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace)
    samples = run(run_prompt_benchmark(
        trace,
        make_llm(usage={}, include_timings=False),
        quality_reviewer=lambda *_: {
            "relevant": True,
            "coherent": True,
            "proportional": True,
            "essential_rules": True,
        },
    ))

    assert samples[0].prompt_tokens is None
    assert samples[0].completion_tokens is None
    assert samples[0].ttft_ms is None
    assert samples[0].output_tokens_per_second is None


def test_prometheus_failure_does_not_fail_inference_or_expose_error_message(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace)

    async def metrics_reader():
        raise RuntimeError("private metrics response body")

    samples = run(
        run_prompt_benchmark(trace, make_llm(), metrics_reader=metrics_reader)
    )
    report = build_benchmark_report(samples)

    assert len(samples) == 10
    assert all(sample.status == "ok" for sample in samples)
    assert all(sample.prometheus_status == "unavailable" for sample in samples)
    assert all(sample.prometheus_error_types == ["RuntimeError"] for sample in samples)
    assert "private metrics response body" not in json.dumps(report)


def test_length_finish_reason_fails_automatic_quality_gate(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace)
    samples = run(run_prompt_benchmark(
        trace,
        make_llm(finish_reason="length"),
        quality_reviewer=lambda *_: {
            "relevant": True,
            "coherent": True,
            "proportional": True,
            "essential_rules": True,
        },
    ))

    assert samples[0].quality_checks["not_truncated"] is False
    assert samples[0].quality_acceptable is False


def test_emoji_violation_fails_automatic_quality_gate(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace)
    llm = make_llm()
    llm.replies = [llm_json("🙂") for _ in range(10)]
    samples = run(run_prompt_benchmark(
        trace,
        llm,
        quality_reviewer=lambda *_: {
            "relevant": True,
            "coherent": True,
            "proportional": True,
            "essential_rules": True,
        },
    ))

    assert samples[0].quality_checks["emoji_free"] is False
    assert samples[0].quality_acceptable is False


def test_failed_sample_is_sanitized_and_does_not_count_as_complete_pair(tmp_path):
    trace = tmp_path / "trace.json"
    make_trace(trace)

    class FailOnceLLM(FakeLLM):
        def __init__(self):
            super().__init__(replies=[llm_json("Respuesta privada") for _ in range(10)])
            self.thinking_mode = "on"
            self.failed = False

        async def chat_with_meta(self, *args, **kwargs):
            if not self.failed:
                self.failed = True
                raise asyncio.TimeoutError("mensaje privado echoed by backend")
            return await super().chat_with_meta(*args, **kwargs)

    samples = run(run_prompt_benchmark(trace, FailOnceLLM()))
    report = build_benchmark_report(samples)

    assert samples[0].status == "failed"
    assert samples[0].error_type == "TimeoutError"
    assert report["complete_pairs"] == 4
    assert report["exploratory_only"] is True
    serialized = json.dumps(report, ensure_ascii=False)
    assert "mensaje privado" not in serialized
    assert "Respuesta privada" not in serialized


def test_report_attributes_call_count_and_repair_purpose(tmp_path):
    """Una muestra con reparación debe mostrar dos llamadas y su motivo."""
    trace = tmp_path / "trace.json"
    make_trace(trace)
    llm = FakeLLM(
        replies=[""] + [llm_json("Respuesta privada")] * 10,
        metas=[LLMMeta(finish_reason="length")]
        + [LLMMeta(finish_reason="stop")] * 10,
    )
    llm.thinking_mode = "on"

    samples = run(run_prompt_benchmark(trace, llm))
    report = build_benchmark_report(samples)

    repaired = samples[0]
    assert repaired.call_count == 2
    assert repaired.primary_finish_reason == "length"
    assert repaired.calls[0]["finish_reason"] == "length"
    assert [call["purpose"] for call in repaired.calls] == [
        "primary",
        "parse_repair",
    ]
    assert isinstance(repaired.repair_ms, int) and repaired.repair_ms >= 0
    assert samples[1].call_count == 1
    assert report["call_purposes"] == {"primary": 10, "parse_repair": 1}
    assert report["variants"]["current"]["call_count"]["median"] == 1
    assert "Respuesta privada" not in json.dumps(report, ensure_ascii=False)
