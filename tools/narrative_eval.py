#!/usr/bin/env python3
"""CLI de evaluación narrativa multi-turno de Airi.

Uso:
    python tools/narrative_eval.py --run registros.jsonl
    python tools/narrative_eval.py --run candidata.jsonl --baseline base.jsonl

El fichero de entrada es JSONL con un registro por turno (ver
`airi.evaluation.narrative`). Mantén el mismo modelo, temperatura y prompts
entre la línea base y la candidata: este script solo compara métricas.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from airi.evaluation.narrative import compare_runs, evaluate_records, load_records  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="JSONL de la ejecución candidata")
    parser.add_argument("--baseline", help="JSONL de la línea base para comparar")
    parser.add_argument(
        "--json", action="store_true", help="Imprime el resultado completo en JSON"
    )
    args = parser.parse_args(argv)

    candidate = load_records(args.run)
    if args.baseline:
        result = compare_runs(load_records(args.baseline), candidate)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result["regression"] else 1

    metrics = evaluate_records(candidate)
    if args.json:
        print(json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2))
    else:
        data = metrics.to_dict()
        print(f"Turnos evaluados: {data['turns']}")
        print(f"Preguntas románticas no solicitadas: {data['unsolicited_romantic_questions']}")
        print(f"Transiciones sin evidencia: {data['transitions_without_evidence']}")
        print(f"Contradicciones de etapa: {data['stage_contradictions']}")
        print(f"Pareja declarada antes de confirmarse: {data['premature_partner_claims']}")
        print(f"Enamoramiento no confirmado: {data['unconfirmed_enamored_claims']}")
        print("OK" if data["passed"] else f"VIOLACIONES: {data['violations']}")
    return 0 if metrics.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
