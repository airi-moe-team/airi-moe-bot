#!/usr/bin/env python3
"""Benchmark A/B de la optimización experimental de tool-template.

Compara el adaptador llama.cpp anterior con la declaración integrada de
`get_datetime` usando los mismos escenarios de Airi, el system prompt completo y
repeticiones emparejadas. No publica en Discord ni persiste estado real.

Uso:
    python tools/tool_template_benchmark.py --live --out benchmark.json
    python tools/tool_template_benchmark.py --live --repeat 5 \
        --records-out registros.jsonl

Solo `--records-out` guarda prompts o respuestas; el resumen agregado no los
incluye. La semilla no se fija porque el adaptador no envía `seed` al backend:
la variabilidad del modelo sigue siendo una limitación del experimento.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:  # El CLI debe leer el .env real, pero los tests lo neutralizan.
    import dotenv

    dotenv.load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover - dotenv es opcional en el tool
    pass

from airi.adapters.http_llm import build_llm  # noqa: E402
from airi.evaluation.interaction import (  # noqa: E402
    EVAL_NOW,
    InteractionScenario,
    generate_live_records,
)

MIN_REPEATS = 5
PILOT_REPEATS = 2
PILOT_SCENARIOS = ("bench_saludo", "bench_historial_largo")


def disable_tool_template_for_baseline(client):
    """Desactiva la declaración solo en el cliente OFF del harness A/B."""
    client._tool_template_active = lambda **kwargs: False


def verify_primary_application(record, *, enabled):
    """Impide publicar comparaciones en las que ON no alcanzó la llamada real."""
    primary = [
        call for call in (record.get("llm_calls") or [])
        if call.get("purpose") == "primary"
    ]
    if len(primary) != 1 or primary[0].get("tool_template_optimization") is not enabled:
        raise ValueError("La llamada principal no aplicó el modo A/B solicitado")
    declared = primary[0].get("declared_tools")
    if (enabled and declared != 1) or (not enabled and declared is not None):
        raise ValueError("La llamada principal declaró herramientas inesperadas")


def save_verified_record(record, *, enabled, sink):
    verify_primary_application(record, enabled=enabled)
    record["tool_template_optimization"] = enabled
    sink(record)

#: Escenarios mínimos solicitados para validar la optimización. La salida
#: estructurada se ejercita en todos los turnos por el flujo actual de Airi y
#: queda fuera de la inyección experimental por diseño.
BENCHMARK_SCENARIOS: tuple[InteractionScenario, ...] = (
    InteractionScenario(
        "bench_saludo",
        "brief_greeting",
        "Saludo inicial breve.",
        ("hola Airi",),
    ),
    InteractionScenario(
        "bench_cumplido",
        "casual",
        "Cumplido y conversación casual.",
        ("Hoy te ves especialmente linda, ¿lo sabías?",),
    ),
    InteractionScenario(
        "bench_factual",
        "direct_question",
        "Pregunta factual directa con opinión.",
        ("Airi, ¿qué prefieres: el café o el té? Dime cuál y por qué.",),
    ),
    InteractionScenario(
        "bench_emocional",
        "emotional",
        "Conversación emocional sobre un día difícil.",
        (
            "Hoy perdí algo que me importaba y no sé cómo sentirme.",
            "Gracias por escucharme. ¿Te ha pasado algo parecido?",
        ),
    ),
    InteractionScenario(
        "bench_historial_largo",
        "casual",
        "Conversación con historial largo acumulado.",
        (
            "Hoy empecé a leer una novela de fantasía.",
            "El protagonista me recuerda un poco a ti.",
            "¿Tú qué harías en su lugar?",
            "Ayer también estuve pensando en eso.",
            "Me gusta hablar contigo de estas cosas.",
            "¿Recuerdas de qué libro te hablé?",
            "Creo que lo voy a terminar esta semana.",
            "¿Qué te parece si te cuento el final cuando termine?",
        ),
    ),
    InteractionScenario(
        "bench_multiusuario",
        "casual",
        "Conversación multiusuario con etiquetas de identidad.",
        (
            "[Kokoda]: Airi, Alex dice que hoy no vino porque estaba cansado.",
            "[Alex]: sí, preferí quedarme en casa. ¿Me regañas?",
        ),
    ),
)


def _median(values):
    clean = [value for value in values if isinstance(value, (int, float))]
    return median(clean) if clean else None


def _sum_valid(values):
    clean = [value for value in values if isinstance(value, (int, float))]
    return sum(clean) if clean else None


def _calls(records):
    return [
        call
        for record in records
        for call in (record.get("llm_calls") or [])
        if isinstance(call, dict)
    ]


def _usage(records, key):
    return [
        record["llm_usage"][key]
        for record in records
        if isinstance(record.get("llm_usage"), dict)
        and isinstance(record["llm_usage"].get(key), (int, float))
        and not isinstance(record["llm_usage"].get(key), bool)
    ]


def select_scenarios(scenario_ids):
    """Selecciona escenarios por id conservando el orden de definición."""
    if not scenario_ids:
        return BENCHMARK_SCENARIOS
    by_id = {scenario.id: scenario for scenario in BENCHMARK_SCENARIOS}
    unknown = [scenario_id for scenario_id in scenario_ids if scenario_id not in by_id]
    if unknown:
        raise ValueError(f"Escenario(s) desconocido(s): {', '.join(unknown)}")
    selected = set(scenario_ids)
    return tuple(scenario for scenario in BENCHMARK_SCENARIOS if scenario.id in selected)


def resolve_repeat(repeat, *, pilot):
    """El benchmark formal exige cinco repeticiones; piloto admite menos."""
    resolved = (PILOT_REPEATS if pilot else MIN_REPEATS) if repeat is None else repeat
    minimum = 1 if pilot else MIN_REPEATS
    if resolved < minimum:
        raise ValueError(
            f"--repeat debe ser >= {minimum} {'en modo pilot' if pilot else 'fuera de pilot'}"
        )
    return resolved


class RecordSink:
    """Conserva en memoria y, opcionalmente, persiste cada registro al llegar."""

    def __init__(self, path=None):
        self.records = []
        self._handle = None
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._handle = target.open("w", encoding="utf-8")

    def __call__(self, record):
        self.records.append(record)
        if self._handle:
            self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._handle.flush()

    def close(self):
        if self._handle:
            self._handle.close()
            self._handle = None


def summarize_records(records, *, enabled: bool) -> dict:
    """Resume una configuración sin serializar prompt ni respuesta."""
    calls = _calls(records)
    replies = [str(record.get("reply") or "") for record in records]
    visible = [bool(reply.strip()) for reply in replies]
    parse_failures = sum(not record.get("parse_ok", True) for record in records)
    truncated = sum(record.get("finish_reason") == "length" for record in records)
    anomalies = sum(
        bool(call.get("synthetic_tool_call_ignored")) for call in calls
    )
    tool_calls = sum(bool(call.get("tool_calls_present")) for call in calls)
    return {
        "tool_template_optimization": enabled,
        "turns": len(records),
        "scenarios": sorted({record.get("scenario") for record in records}),
        "visible_replies": sum(visible),
        "empty_replies": len(visible) - sum(visible),
        "parse_failures": parse_failures,
        "truncated_finish_length": truncated,
        "tool_call_anomalies_ignored": anomalies,
        "tool_calls_present": tool_calls,
        "declared_tools": max(
            (
                call["declared_tools"]
                for call in calls
                if isinstance(call.get("declared_tools"), int)
            ),
            default=None,
        ),
        "prompt_tokens_total": _sum_valid(_usage(records, "prompt_tokens")),
        "completion_tokens_total": _sum_valid(_usage(records, "completion_tokens")),
        "completion_tokens_median": _median(_usage(records, "completion_tokens")),
        "reasoning_tokens_median": _median(
            [
                call["reasoning_tokens"]
                for call in calls
                if isinstance(call.get("reasoning_tokens"), int)
            ]
        ),
        "reasoning_chars_median": _median(
            [
                call["reasoning_chars"]
                for call in calls
                if isinstance(call.get("reasoning_chars"), int)
            ]
        ),
        "ttft_ms_median": _median(
            [
                call["ttft_ms"]
                for call in calls
                if isinstance(call.get("ttft_ms"), int)
            ]
        ),
        "first_content_ms_median": _median(
            [
                call["first_content_ms"]
                for call in calls
                if isinstance(call.get("first_content_ms"), int)
            ]
        ),
        "turn_latency_ms_median": _median(
            [
                record.get("total_latency_ms")
                for record in records
                if isinstance(record.get("total_latency_ms"), int)
            ]
        ),
        "finish_reasons": {
            reason: sum(
                record.get("finish_reason") == reason for record in records
            )
            for reason in sorted(
                {
                    str(record.get("finish_reason"))
                    for record in records
                    if record.get("finish_reason") is not None
                }
            )
        },
    }


def build_report(off_records, on_records) -> dict:
    baseline = summarize_records(off_records, enabled=False)
    candidate = summarize_records(on_records, enabled=True)
    deltas = {}
    for key in (
        "visible_replies",
        "empty_replies",
        "parse_failures",
        "truncated_finish_length",
        "prompt_tokens_total",
        "completion_tokens_total",
        "completion_tokens_median",
        "reasoning_chars_median",
        "ttft_ms_median",
        "first_content_ms_median",
        "turn_latency_ms_median",
    ):
        before, after = baseline.get(key), candidate.get(key)
        deltas[key] = (
            after - before
            if isinstance(before, (int, float)) and isinstance(after, (int, float))
            else None
        )
    return {
        "feature": "airi-optimizacion-tool-template-llama",
        "experimental": True,
        "baseline": baseline,
        "candidate": candidate,
        "candidate_minus_baseline": deltas,
        "quality_review_required": True,
        "limitations": [
            "No se fija semilla: el adaptador no envía `seed` al backend.",
            "Los caracteres de razonamiento son una aproximación, no tokens.",
            "Las conversaciones usan el harness de evaluación, no Discord real.",
            "La validez conversacional exige revisión humana de muestras.",
            "El resumen no incluye prompts ni respuestas; usa --records-out de forma explícita.",
        ],
    }


async def run_live(
    *, repeat: int, base_url: str | None, model: str | None,
    scenarios=BENCHMARK_SCENARIOS, records_out=None,
) -> tuple[list[dict], list[dict]]:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        off_client = build_llm(
            session,
            base_url=base_url,
            model=model,
        )
        on_client = build_llm(
            session,
            base_url=base_url,
            model=model,
        )
        disable_tool_template_for_baseline(off_client)
        sink = RecordSink(records_out)
        try:
            off_records = []
            on_records = []
            # Ejecución emparejada por repetición/escenario; se invierte el
            # orden en pares sucesivos para amortiguar deriva del servidor.
            for repeat_index in range(repeat):
                for scenario_index, scenario in enumerate(scenarios):
                    variants = (
                        ((False, off_client), (True, on_client))
                        if (repeat_index + scenario_index) % 2 == 0
                        else ((True, on_client), (False, off_client))
                    )
                    for enabled, client in variants:
                        record_start = len(sink.records)
                        await generate_live_records(
                            llm=client,
                            scenarios=(scenario,),
                            repeat=1,
                            now=EVAL_NOW,
                            base_url=base_url,
                            model=model,
                            on_record=lambda record, flag=enabled: save_verified_record(
                                record, enabled=flag, sink=sink
                            ),
                        )
                        (on_records if enabled else off_records).extend(
                            sink.records[record_start:]
                        )
                        print(
                            f"progreso: {len(sink.records)} "
                            f"registros; último={scenario.id} modo={'ON' if enabled else 'OFF'}",
                            file=sys.stderr,
                            flush=True,
                        )
            return off_records, on_records
        finally:
            sink.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Genera el benchmark contra el LLM"
    )
    parser.add_argument("--pilot", action="store_true", help="Permite menos de cinco repeticiones")
    parser.add_argument(
        "--repeat",
        type=int,
        default=None,
        help="Repeticiones por escenario y modo (5 formal; 2 por defecto en piloto)",
    )
    parser.add_argument(
        "--scenario", action="append", dest="scenarios",
        help="Id de escenario a incluir (puede repetirse; por defecto todos)",
    )
    parser.add_argument("--base-url", help="Endpoint (por defecto LLM_BASE_URL)")
    parser.add_argument("--model", help="Modelo explícito (por defecto LLM_MODEL)")
    parser.add_argument("--out", help="Ruta del resumen JSON")
    parser.add_argument(
        "--records-out",
        help="JSONL opcional con prompts/respuestas; es una salida sensible",
    )
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live es obligatorio")
    try:
        repeat = resolve_repeat(args.repeat, pilot=args.pilot)
        scenarios = select_scenarios(
            args.scenarios if args.scenarios else (PILOT_SCENARIOS if args.pilot else None)
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        off_records, on_records = asyncio.run(
            run_live(
                repeat=repeat,
                base_url=args.base_url,
                model=args.model,
                scenarios=scenarios,
                records_out=args.records_out,
            )
        )
    except Exception as exc:  # noqa: BLE001 - el CLI informa y falla
        print(f"No se pudo generar el benchmark: {exc}", file=sys.stderr)
        return 2
    report = build_report(off_records, on_records)
    report["configuration"] = {
        "comparison": "baseline del harness frente a declaración integrada",
        "base_url": args.base_url or os.environ.get("LLM_BASE_URL"),
        "model": args.model or os.environ.get("LLM_MODEL"),
        "repeat": repeat,
        "pilot": args.pilot,
        "scenarios": [scenario.id for scenario in scenarios],
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.records_out:
        print(f"Registros sensibles en {args.records_out}", file=sys.stderr)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(f"Resumen guardado en {args.out}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
