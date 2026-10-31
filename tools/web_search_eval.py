#!/usr/bin/env python3
"""Evalúa la decisión y la síntesis conversacional de la búsqueda web.

Uso:
    .venv/bin/python tools/web_search_eval.py --live --out eval/web-search.jsonl --judge
    .venv/bin/python tools/web_search_eval.py --run eval/web-search.jsonl
    .venv/bin/python tools/web_search_eval.py --live --out eval/web-search.jsonl

La evaluación live usa el modelo configurado en ``.env`` y notas web
deterministas; no consulta Brave ni Discord. Con ``--judge`` se aplica el mismo
LLM como juez semántico, secuencialmente. Sin ese flag, los registros quedan
disponibles para revisión manual.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:  # el CLI usa el .env del proyecto; las pruebas no invocan este loader
    import dotenv

    dotenv.load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover - dotenv es opcional
    pass

from airi.evaluation.interaction import load_records, write_records  # noqa: E402
from airi.evaluation.web_search import (  # noqa: E402
    WEB_SEARCH_SCENARIOS,
    append_web_search_records,
    evaluate_web_search_records,
    generate_web_search_records,
    judge_web_search_records,
)


async def _live(args, *, on_records=None):
    import aiohttp

    from airi.adapters.http_llm import build_llm

    scenarios = tuple(
        scenario
        for scenario in WEB_SEARCH_SCENARIOS
        if not args.scenario or scenario.id in args.scenario
    )
    async with aiohttp.ClientSession() as session:
        llm = build_llm(session, base_url=args.base_url, model=args.model)
        records = []
        for repeat in range(1, args.repeat + 1):
            for scenario in scenarios:
                current = await generate_web_search_records(
                    llm=llm,
                    scenarios=(scenario,),
                )
                for record in current:
                    record["repeat"] = repeat
                if args.judge:
                    current = await judge_web_search_records(llm, current)
                records.extend(current)
                if on_records is not None:
                    on_records(current)
                print(
                    f"Caso completado: {scenario.id}", file=sys.stderr
                )
    return records


async def _judge_existing(args, records):
    import aiohttp

    from airi.adapters.http_llm import build_llm

    async with aiohttp.ClientSession() as session:
        llm = build_llm(session, base_url=args.base_url, model=args.model)
        return await judge_web_search_records(llm, records)


def _print_report(report: dict) -> None:
    print(f"Escenarios: {report['scenarios']}")
    print(
        "Decisión de búsqueda: accuracy={accuracy} precision={precision} recall={recall} "
        "(TP={tp}, FP={fp}, FN={fn}, TN={tn})".format(
            accuracy=report["decision_accuracy"],
            precision=report["precision"],
            recall=report["recall"],
            tp=report["true_positive"],
            fp=report["false_positive"],
            fn=report["false_negative"],
            tn=report["true_negative"],
        )
    )
    if report["semantic_opportunities"]:
        print(
            f"Juez semántico: {report['semantic_score']}/"
            f"{report['semantic_opportunities']} puntos en "
            f"{report['semantic_cases_scored']} casos"
        )
    else:
        print("Juez semántico: sin etiquetas válidas")
    for case in report["cases"]:
        print(
            f"- {case['scenario']}: {case['decision']}"
            + (
                f"; juicio={case['semantic_judgment'].get('rationale', '')}"
                if case.get("semantic_judgment")
                else ""
            )
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--live", action="store_true", help="Ejecuta los ocho casos")
    source.add_argument("--run", help="Evalúa un JSONL ya generado")
    parser.add_argument(
        "--out", help="JSONL de salida con --live o para guardar juicios de --run"
    )
    parser.add_argument("--base-url", help="Endpoint del LLM (por defecto LLM_BASE_URL)")
    parser.add_argument("--model", help="Modelo explícito (por defecto LLM_MODEL)")
    parser.add_argument("--repeat", type=int, default=1, help="Repeticiones completas")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=tuple(scenario.id for scenario in WEB_SEARCH_SCENARIOS),
        help="Ejecuta solo este escenario (puede repetirse)",
    )
    parser.add_argument(
        "--judge", action="store_true",
        help="Evalúa la síntesis con un juez LLM local (añade llamadas al modelo)",
    )
    parser.add_argument("--json", action="store_true", help="Imprime el informe JSON")
    args = parser.parse_args(argv)

    if args.repeat < 1:
        parser.error("--repeat debe ser >= 1")
    if args.live:
        if not args.out:
            parser.error("--out es obligatorio con --live")
        if args.scenario and args.repeat != 1:
            parser.error("--repeat con escenarios seleccionados repetiría solo esos escenarios")
        write_records(args.out, [])
        try:
            records = asyncio.run(
                _live(
                    args,
                    on_records=lambda batch: append_web_search_records(
                        args.out, batch
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001 - error visible al operador
            print(f"Falló la evaluación live: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(f"Registros guardados: {args.out}", file=sys.stderr)
    else:
        if args.scenario:
            parser.error("--scenario solo se usa con --live")
        records = load_records(args.run)
        if args.judge:
            try:
                records = asyncio.run(_judge_existing(args, records))
            except Exception as exc:  # noqa: BLE001 - error visible al operador
                print(f"Falló el juez semántico: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 2
        if args.out:
            write_records(args.out, records)
            print(f"Registros guardados: {args.out}", file=sys.stderr)

    report = evaluate_web_search_records(records)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
