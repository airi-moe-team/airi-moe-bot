#!/usr/bin/env python3
"""CLI de evaluación de interacción natural de Airi.

Uso:
    python tools/interaction_eval.py --live --out baseline.jsonl
    python tools/interaction_eval.py --run candidata.jsonl --baseline base.jsonl
    python tools/interaction_eval.py --live --out candidata.jsonl --baseline base.jsonl

``--live`` genera los siete escenarios contra el LLM configurado (por defecto
``LLM_BASE_URL`` o ``http://127.0.0.1:7000``) usando ``ConversationService``.
No publica en Discord ni persiste estado real. ``--run`` analiza un JSONL ya
generado. El modo live no se ejecuta en la suite automática sin red.

La rúbrica 0-2 por criterio se añade al revisar el JSONL. Cada escenario vale
10 puntos; los siete suman 70.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:  # El CLI debe leer el .env real, pero los tests lo neutralizan.
    import dotenv

    dotenv.load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover - dotenv es opcional en el tool
    pass

from airi.evaluation.interaction import (  # noqa: E402
    compare_interactions,
    evaluate_interactions,
    generate_live_records,
    load_records,
    write_records,
)


def _print_metrics(metrics: dict, *, prefix: str = "") -> None:
    label = f"{prefix}: " if prefix else ""
    print(f"{label}Turnos evaluados: {metrics['turns']}")
    print(f"{label}Escenarios: {len(metrics['scenarios'])}")
    print(f"{label}Preguntas como cierre: {metrics['question_only_replies']}")
    print(f"{label}Cierres repetidos: {metrics['repeated_closings']}")
    print(f"{label}Gestos por respuesta: {metrics['gesture_density']}")
    print(f"{label}Respuestas con gestos acumulados: {metrics['stacked_gestures']}")
    print(f"{label}Muletillas de despedida: {metrics['prefab_farewells']}")
    print(f"{label}Fallos de esquema: {metrics['schema_failures']}")
    print(f"{label}Respuestas truncadas: {metrics['truncated_replies']}")
    print(f"{label}Contradicciones de estado: {metrics['state_contradictions']}")
    print(f"{label}Respuestas desproporcionadas: {metrics['disproportionate_replies']}")
    print(
        f"{label}Rúbrica: {metrics['rubric_total']}/{metrics['rubric_max']} "
        f"({metrics['rubric_scenarios_scored']} escenarios puntuados)"
    )
    verdict = "OK" if metrics["passed"] else "FALLOS CRÍTICOS"
    print(f"{label}{verdict}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", help="JSONL ya generado")
    source.add_argument(
        "--live",
        action="store_true",
        help="Genera los siete escenarios contra el LLM configurado",
    )
    parser.add_argument("--baseline", help="JSONL de la línea base para comparar")
    parser.add_argument(
        "--out",
        help="JSONL de salida para --live (obligatorio en modo live)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Imprime el resultado completo en JSON"
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Repeticiones por escenario en modo live (muestreo no determinista)",
    )
    parser.add_argument(
        "--base-url",
        help="Endpoint del LLM para --live (por defecto LLM_BASE_URL)",
    )
    parser.add_argument(
        "--model",
        help="Modelo explícito para --live (por defecto LLM_MODEL)",
    )
    args = parser.parse_args(argv)

    if args.live:
        if not args.out:
            parser.error("--out es obligatorio con --live")
        if args.repeat < 1:
            parser.error("--repeat debe ser >= 1")
        try:
            candidate = asyncio.run(
                generate_live_records(
                    repeat=args.repeat,
                    base_url=args.base_url,
                    model=args.model,
                )
            )
        except Exception as exc:  # noqa: BLE001 - el CLI informa y falla
            print(f"No se pudo generar la evaluación live: {exc}", file=sys.stderr)
            return 2
        write_records(args.out, candidate)
        print(f"Registros guardados en {args.out}", file=sys.stderr)
    else:
        if args.out:
            parser.error("--out solo se usa con --live")
        candidate = load_records(args.run)

    if args.baseline:
        result = compare_interactions(load_records(args.baseline), candidate)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_metrics(result["baseline"], prefix="Baseline")
            _print_metrics(result["candidate"], prefix="Candidato")
            print(f"Delta de rúbrica: {result['rubric_delta']:+d}")
            if result["critical_regression"]:
                print("REGRESIÓN CRÍTICA")
            elif result["quality_regression"]:
                print("Regresión de calidad (no crítica)")
            else:
                print("Sin regresiones")
        failed = result["regression"] or result["candidate"]["critical_violations"] > 0
        return 1 if failed else 0

    metrics = evaluate_interactions(candidate)
    if args.json:
        print(json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_metrics(metrics.to_dict())
    return 0 if metrics.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
