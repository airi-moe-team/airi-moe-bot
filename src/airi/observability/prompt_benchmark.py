"""Benchmark A/B local de system prompts sobre una traza, sin guardar texto."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Awaitable, Callable, Mapping

import aiohttp

import airi.env_boot  # noqa: F401 — dotenv antes de cargar settings/adapters.
from airi.adapters.http_llm import LLM_THINKING_MODES, build_llm
from airi.domain.prompts import PromptVariant
from airi.domain.text_filters import (
    DISCORD_ASSET_LINK_RE,
    DISCORD_ASSET_URL_RE,
    DISCORD_CUSTOM_EMOJI_RE,
    EMOJI_MODIFIERS_RE,
    EMOJI_RE,
)
from airi.observability.prometheus_metrics import (
    diff_prometheus_metrics,
    parse_prometheus_text,
)
from airi.observability.replay import _mount_event
from airi.observability.trace import load_turn_trace
from airi.services.conversation import ConversationService, TurnContext

MIN_PAIRS = 5
SESSION_KINDS = {"spectator", "active", "proactive"}
VARIANT_ORDER: tuple[PromptVariant, PromptVariant] = (
    "current",
    "compact_candidate",
)
QUALITY_REVIEW_KEYS = ("relevant", "coherent", "proportional", "essential_rules")
METRIC_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "llm_ms",
    "total_ms",
    "ttft_ms",
    "first_content_ms",
    "output_tokens_per_second",
    "reasoning_tokens",
    "call_count",
    "repair_ms",
)
#: Únicos campos de una llamada que se copian al reporte (nunca texto).
CALL_METADATA_FIELDS = (
    "purpose",
    "status",
    "duration_ms",
    "finish_reason",
    "usage",
    "ttft_ms",
    "first_content_ms",
    "server_timings",
    "reasoning_present",
    "reasoning_tokens",
    "reasoning_budget_tokens",
    "reasoning_deltas",
    "content_deltas",
    "max_tokens",
    "error_type",
)


@dataclass
class BenchmarkSample:
    """Una medición serializable; no contiene entrada, prompt ni respuesta."""

    trace_id: str
    variant: PromptVariant
    pair_index: int
    order: str
    thinking_mode: str = "auto"
    max_output_tokens: int | None = None
    status: str = "ok"
    prompt_sha256: str | None = None
    prompt_chars: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    llm_ms: int | None = None
    total_ms: int | None = None
    ttft_ms: int | None = None
    first_content_ms: int | None = None
    output_tokens_per_second: float | None = None
    server_timings: dict[str, int | float] | None = None
    reasoning_present: bool | None = None
    reasoning_tokens: int | None = None
    call_count: int | None = None
    repair_ms: int | None = None
    primary_finish_reason: str | None = None
    call_purposes: list[str] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    prometheus_status: str = "disabled"
    prometheus_scope: str | None = None
    prometheus_deltas: list[dict] = field(default_factory=list)
    prometheus_error_types: list[str] = field(default_factory=list)
    finish_reason: str | None = None
    quality_checks: dict[str, bool | None] = field(default_factory=dict)
    quality_acceptable: bool | None = None
    quality_review_pending: bool = True
    error_type: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _optional_int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _sanitized_calls(trace) -> list[dict]:
    """Copia de los metadatos por llamada, restringida a campos conocidos."""
    raw = getattr(trace, "llm_calls", None) or []
    return [
        {key: call.get(key) for key in CALL_METADATA_FIELDS}
        for call in raw
        if isinstance(call, Mapping)
    ]


def _repair_ms(calls: list[dict]) -> int | None:
    if len(calls) < 2:
        return None
    return sum(int(call.get("duration_ms") or 0) for call in calls[1:])


def _contains_emoji(text: str) -> bool:
    return any(
        pattern.search(text)
        for pattern in (
            EMOJI_RE,
            EMOJI_MODIFIERS_RE,
            DISCORD_CUSTOM_EMOJI_RE,
            DISCORD_ASSET_LINK_RE,
            DISCORD_ASSET_URL_RE,
        )
    )


def _raw_model_reply(raw_llm: str | None, fallback: str) -> str:
    try:
        decoded = json.loads(raw_llm or "")
    except (TypeError, json.JSONDecodeError):
        return fallback
    if isinstance(decoded, dict) and isinstance(decoded.get("reply"), str):
        return decoded["reply"]
    return fallback


def _quality_checks(
    trace, reply: str, raw_reply: str, semantic_review: Mapping | None
):
    checks: dict[str, bool | None] = {
        "schema_valid": bool(trace.parse_ok),
        "reply_nonempty": bool(reply.strip()),
        "not_truncated": trace.llm_finish_reason != "length",
        "emoji_free": not _contains_emoji(raw_reply),
    }
    for key in QUALITY_REVIEW_KEYS:
        value = semantic_review.get(key) if isinstance(semantic_review, Mapping) else None
        checks[key] = value if isinstance(value, bool) else None
    pending = any(checks[key] is None for key in QUALITY_REVIEW_KEYS)
    if any(not value for value in checks.values() if value is not None):
        acceptable = False
    elif pending:
        acceptable = None
    else:
        acceptable = True
    return checks, acceptable, pending


def _sample_from_result(
    event,
    result,
    *,
    variant: PromptVariant,
    thinking_mode: str,
    max_output_tokens: int | None,
    pair_index: int,
    order: str,
    quality_reviewer: Callable[[str, str, PromptVariant], Mapping[str, bool | None]]
    | None,
) -> BenchmarkSample:
    trace = result.trace
    if trace is None:
        raise RuntimeError("TurnResult sin traza de métricas")
    prompt = trace.prompt_system or ""
    reply = result.reply or ""
    raw_reply = _raw_model_reply(trace.raw_llm, reply)
    usage = trace.llm_usage if isinstance(trace.llm_usage, Mapping) else {}
    completion_tokens = _optional_int(usage.get("completion_tokens"))
    llm_ms = _optional_int(trace.llm_latency_ms)
    rate = (
        completion_tokens / (llm_ms / 1000)
        if completion_tokens is not None and llm_ms is not None and llm_ms > 0
        else None
    )
    semantic_review = None
    if quality_reviewer is not None:
        user_text = event.raw_input or "\n".join(
            str(message.get("text", "")) for message in event.messages_in
        )
        try:
            semantic_review = quality_reviewer(user_text, reply, variant)
        except Exception:
            # El contenido de la excepción puede incorporar texto privado.
            semantic_review = None
    quality, acceptable, pending = _quality_checks(
        trace, reply, raw_reply, semantic_review
    )
    calls = _sanitized_calls(trace)
    return BenchmarkSample(
        trace_id=event.correlation_id,
        variant=variant,
        thinking_mode=thinking_mode,
        max_output_tokens=max_output_tokens,
        pair_index=pair_index,
        order=order,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        prompt_chars=len(prompt),
        prompt_tokens=_optional_int(usage.get("prompt_tokens")),
        completion_tokens=completion_tokens,
        total_tokens=_optional_int(usage.get("total_tokens")),
        llm_ms=llm_ms,
        total_ms=_optional_int(trace.total_latency_ms),
        ttft_ms=_optional_int(trace.llm_ttft_ms),
        first_content_ms=_optional_int(trace.llm_first_content_ms),
        output_tokens_per_second=rate,
        server_timings=trace.llm_server_timings,
        reasoning_present=trace.llm_reasoning_present,
        reasoning_tokens=_optional_int(trace.llm_reasoning_tokens),
        call_count=len(calls) or None,
        repair_ms=_repair_ms(calls),
        primary_finish_reason=(
            calls[0].get("finish_reason") if calls else None
        ),
        call_purposes=[str(call.get("purpose")) for call in calls],
        calls=calls,
        finish_reason=trace.llm_finish_reason,
        quality_checks=quality,
        quality_acceptable=acceptable,
        quality_review_pending=pending,
    )


async def _read_metrics_snapshot(metrics_reader):
    if metrics_reader is None:
        return None, None
    try:
        snapshot = await metrics_reader()
        if not isinstance(snapshot, Mapping):
            return None, "InvalidMetricsSnapshot"
        return snapshot, None
    except Exception as exc:
        # No se guarda el cuerpo/respuesta de Prometheus ni el mensaje libre.
        return None, type(exc).__name__


async def run_prompt_benchmark(
    trace_path: str | Path,
    llm,
    *,
    pair_count: int = MIN_PAIRS,
    quality_reviewer: Callable[[str, str, PromptVariant], Mapping[str, bool | None]]
    | None = None,
    metrics_reader: Callable[[], Awaitable[Mapping]] | None = None,
    thinking_mode: str = "auto",
    max_output_tokens: int | None = None,
) -> list[BenchmarkSample]:
    """Ejecuta pares limpios; exige un perfil global de thinking verificable."""
    if pair_count < MIN_PAIRS:
        raise ValueError(f"El benchmark requiere al menos cinco pares (recibido: {pair_count})")
    if thinking_mode not in LLM_THINKING_MODES:
        raise ValueError(
            "thinking_mode debe ser 'auto', 'low', 'medium' o 'high'"
        )
    if getattr(llm, "thinking_mode", None) != thinking_mode:
        raise ValueError(
            f"El benchmark exige thinking mode {thinking_mode} configurado y "
            "verificable en el cliente"
        )
    if max_output_tokens is not None and (
        not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens <= 0
    ):
        raise ValueError("max_output_tokens debe ser un entero positivo")

    event = load_turn_trace(trace_path)
    if not event.messages_in or not event.user_id:
        raise ValueError("La traza debe contener user_id y al menos un mensaje de entrada")

    samples: list[BenchmarkSample] = []
    for pair_index in range(1, pair_count + 1):
        order_variants = (
            VARIANT_ORDER if pair_index % 2 else tuple(reversed(VARIANT_ORDER))
        )
        order = "AB" if pair_index % 2 else "BA"
        for variant in order_variants:
            metrics_before, metrics_before_error = await _read_metrics_snapshot(
                metrics_reader
            )
            try:
                state, _uid, user, messages = _mount_event(event)
                service = ConversationService(
                    llm=llm,
                    state=state,
                    search=None,
                    gifs=None,
                    notifier=None,
                    clock=lambda: event.started_at or 0.0,
                    traces=None,
                )
                result = await service.run_turn(
                    user,
                    messages,
                    TurnContext(
                        channel_id=0,
                        allow_web=False,
                        correlation_id=(
                            f"{event.correlation_id}-bench-{pair_index}-{variant}"
                        ),
                        conversation_mode=(
                            event.kind if event.kind in SESSION_KINDS else "normal"
                        ),
                        system_prompt_variant=variant,
                        stream_llm=True,
                        llm_max_tokens=max_output_tokens,
                    ),
                )
                sample = _sample_from_result(
                    event,
                    result,
                    variant=variant,
                    thinking_mode=thinking_mode,
                    max_output_tokens=max_output_tokens,
                    pair_index=pair_index,
                    order=order,
                    quality_reviewer=quality_reviewer,
                )
            except Exception as exc:
                # No se guarda el mensaje de excepción: un servidor puede ecoar el prompt.
                sample = BenchmarkSample(
                    trace_id=event.correlation_id,
                    variant=variant,
                    thinking_mode=thinking_mode,
                    max_output_tokens=max_output_tokens,
                    pair_index=pair_index,
                    order=order,
                    status="failed",
                    quality_review_pending=True,
                    error_type=type(exc).__name__,
                )
            metrics_after, metrics_after_error = await _read_metrics_snapshot(
                metrics_reader
            )
            if metrics_reader is not None:
                sample.prometheus_scope = "aggregate_snapshot_delta"
                errors = [
                    error
                    for error in (metrics_before_error, metrics_after_error)
                    if error is not None
                ]
                if errors or metrics_before is None or metrics_after is None:
                    sample.prometheus_status = "unavailable"
                    sample.prometheus_error_types = sorted(set(errors))
                else:
                    sample.prometheus_status = "ok"
                    sample.prometheus_deltas = diff_prometheus_metrics(
                        metrics_before, metrics_after
                    )
            samples.append(sample)
    return samples


def _metric_summary(samples: list[BenchmarkSample]) -> dict:
    summary = {}
    for metric in METRIC_FIELDS:
        values = [
            getattr(sample, metric)
            for sample in samples
            if sample.status == "ok" and getattr(sample, metric) is not None
        ]
        summary[metric] = (
            {
                "count": len(values),
                "median": median(values),
                "min": min(values),
                "max": max(values),
            }
            if values
            else {"count": 0, "median": None, "min": None, "max": None}
        )
    return summary


def build_benchmark_report(samples: list[BenchmarkSample]) -> dict:
    """Resume métricas por brazo sin serializar texto conversacional."""
    variants = {
        variant: _metric_summary([s for s in samples if s.variant == variant])
        for variant in VARIANT_ORDER
    }
    server_timing_summaries = {}
    for variant in VARIANT_ORDER:
        variant_samples = [
            sample for sample in samples
            if sample.variant == variant and sample.status == "ok"
        ]
        timing_keys = sorted({
            key
            for sample in variant_samples
            for key in (sample.server_timings or {})
        })
        server_timing_summaries[variant] = {
            key: _numeric_summary([
                sample.server_timings[key]
                for sample in variant_samples
                if sample.server_timings and key in sample.server_timings
            ])
            for key in timing_keys
        }
    indexed = {(sample.pair_index, sample.variant): sample for sample in samples}
    complete_pairs = [
        pair_index
        for pair_index in sorted({sample.pair_index for sample in samples})
        if all(
            (pair_index, variant) in indexed
            and indexed[(pair_index, variant)].status == "ok"
            for variant in VARIANT_ORDER
        )
    ]
    paired_deltas = {}
    for metric in METRIC_FIELDS:
        deltas = [
            getattr(indexed[(pair_index, "compact_candidate")], metric)
            - getattr(indexed[(pair_index, "current")], metric)
            for pair_index in complete_pairs
            if getattr(indexed[(pair_index, "compact_candidate")], metric) is not None
            and getattr(indexed[(pair_index, "current")], metric) is not None
        ]
        paired_deltas[metric] = (
            {"count": len(deltas), "median": median(deltas)}
            if deltas
            else {"count": 0, "median": None}
        )

    candidate_samples = [
        sample for sample in samples if sample.variant == "compact_candidate"
    ]
    if any(sample.quality_acceptable is False for sample in candidate_samples):
        candidate_acceptable = False
    elif (
        len(complete_pairs) >= MIN_PAIRS
        and candidate_samples
        and all(sample.quality_acceptable is True for sample in samples)
    ):
        candidate_acceptable = True
    else:
        candidate_acceptable = None

    return {
        "trace_id": samples[0].trace_id if samples else None,
        "generation_profile": {
            "thinking_mode": samples[0].thinking_mode if samples else None,
            "max_output_tokens": samples[0].max_output_tokens if samples else None,
        },
        "minimum_pairs": MIN_PAIRS,
        "sample_count": len(samples),
        "failed_samples": sum(sample.status != "ok" for sample in samples),
        "complete_pairs": len(complete_pairs),
        "exploratory_only": len(complete_pairs) < MIN_PAIRS,
        "variants": variants,
        "server_timings": server_timing_summaries,
        "paired_delta_candidate_minus_current": paired_deltas,
        "prometheus_status_counts": {
            status: sum(sample.prometheus_status == status for sample in samples)
            for status in ("disabled", "ok", "unavailable")
        },
        "prometheus_scope": (
            "aggregate_snapshot_delta"
            if any(sample.prometheus_scope for sample in samples)
            else None
        ),
        "call_purposes": {
            purpose: sum(
                sample.call_purposes.count(purpose) for sample in samples
            )
            for purpose in sorted(
                {purpose for sample in samples for purpose in sample.call_purposes}
            )
        },
        "candidate_acceptable": candidate_acceptable,
        "quality_review_pending": any(sample.quality_review_pending for sample in samples),
        "samples": [sample.to_dict() for sample in samples],
        "limitations": [
            "TTFT es tiempo cliente hasta el primer delta; puede incluir cola y transporte.",
            "Timings internos y TTFT miden fases distintas; no deben sumarse sin validar su definición.",
            "La variabilidad del modelo y del servidor no se elimina con el orden alternado.",
            "La aceptación requiere revisión semántica además de los checks automáticos.",
            "Prometheus usa deltas agregados; actividad externa puede contaminar la atribución por muestra.",
            "`call_count`, `repair_ms` y `calls` provienen de la traza: en trazas antiguas quedan nulos.",
            "TTFT y server_timings describen la primera llamada; llm_ms incluye las reparaciones.",
        ],
    }


def _numeric_summary(values: list[int | float]) -> dict:
    return (
        {
            "count": len(values),
            "median": median(values),
            "min": min(values),
            "max": max(values),
        }
        if values
        else {"count": 0, "median": None, "min": None, "max": None}
    )


def _interactive_quality_review(user_text: str, reply: str, variant: PromptVariant):
    """Revisión local opcional: muestra contenido solo en terminal y no lo guarda."""
    print(f"\n[{variant}] Mensaje de referencia:\n{user_text}", file=sys.stderr)
    print(f"Respuesta generada:\n{reply}", file=sys.stderr)
    ratings = {}
    for key in QUALITY_REVIEW_KEYS:
        while True:
            answer = input(f"{key} [s/n]: ").strip().casefold()
            if answer in ("s", "si", "sí"):
                ratings[key] = True
                break
            if answer == "n":
                ratings[key] = False
                break
    return ratings


async def _fetch_prometheus_snapshot(session, url: str):
    timeout = aiohttp.ClientTimeout(total=3)
    async with session.get(url, timeout=timeout) as response:
        response.raise_for_status()
        return parse_prometheus_text(await response.text())


async def _run_cli(
    trace_path: str,
    pair_count: int,
    review: bool,
    metrics_url: str | None,
    thinking_mode: str,
    max_output_tokens: int | None,
) -> dict:
    previous_mode = os.environ.get("LLM_THINKING_MODE")
    os.environ["LLM_THINKING_MODE"] = thinking_mode
    try:
        async with aiohttp.ClientSession() as session:
            llm = build_llm(session)
            samples = await run_prompt_benchmark(
                trace_path,
                llm,
                pair_count=pair_count,
                quality_reviewer=_interactive_quality_review if review else None,
                metrics_reader=(
                    (lambda: _fetch_prometheus_snapshot(session, metrics_url))
                    if metrics_url
                    else None
                ),
                thinking_mode=thinking_mode,
                max_output_tokens=max_output_tokens,
            )
    finally:
        if previous_mode is None:
            os.environ.pop("LLM_THINKING_MODE", None)
        else:
            os.environ["LLM_THINKING_MODE"] = previous_mode
    return build_benchmark_report(samples)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compara prompts y perfiles de generación de Airi con streaming/TTFT.",
        epilog=(
            "Para timings internos de llama-server, habilita --perf al iniciarlo; "
            "para snapshots agrega --metrics-url http://127.0.0.1:7000/metrics "
            "y arráncalo con --metrics. --expert-stats no mide tiempos. "
            "Confirma flags con el --help del build local."
        ),
    )
    parser.add_argument("trace", help="Ruta a la traza de referencia")
    parser.add_argument("--pairs", type=int, default=MIN_PAIRS)
    parser.add_argument(
        "--thinking-mode", choices=LLM_THINKING_MODES, default="auto",
        help="Perfil global fijado para esta corrida (por defecto on)",
    )
    parser.add_argument(
        "--max-output-tokens", type=int,
        help="Límite opcional de salida, aplicado a llamadas y reparaciones",
    )
    parser.add_argument(
        "--metrics-url",
        help="endpoint Prometheus opcional; los deltas se etiquetan como agregados",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="revisión semántica interactiva; muestra texto localmente y no lo guarda",
    )
    parser.add_argument("--out", help="ruta opcional para guardar el JSON agregado")
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(
            _run_cli(
                args.trace, args.pairs, args.review, args.metrics_url,
                args.thinking_mode, args.max_output_tokens,
            )
        )
    except Exception as exc:
        # Evita imprimir mensajes que pudieran contener texto de la traza.
        print(f"ERROR benchmark: {type(exc).__name__}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if report["complete_pairs"] >= MIN_PAIRS else 1


if __name__ == "__main__":
    raise SystemExit(main())
