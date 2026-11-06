"""Barrido local de presupuestos de reasoning sobre hilos sintéticos de Airi.

El reporte incluye respuestas generadas únicamente porque todas las entradas
son sintéticas; no acepta ni lee trazas o conversaciones privadas.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import aiohttp

import airi.env_boot  # noqa: F401
from airi.adapters.http_llm import build_llm
from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeUser, make_state

USER = FakeUser(42, "Alex")
DEPTHS = (0, 8, 20)
DEFAULT_BUDGETS = (256, 512, 1024, 2048, 4096)
DEFAULT_MIN_PASS_RATE = 0.9
HUMAN_REVIEW_DIMENSIONS = (
    "spanish_naturalness",
    "coherence",
    "context_fidelity",
    "relevance",
    "reflective_quality",
)
HUMAN_REVIEW_LABELS = {
    "spanish_naturalness": "Español: gramática, concordancia y naturalidad",
    "coherence": "Coherencia: sentido y conexión entre las ideas",
    "context_fidelity": "Fidelidad: respeta el hilo y separa hechos de inferencias",
    "relevance": "Pertinencia: responde a lo preguntado sin desviarse",
    "reflective_quality": "Reflexión: aporta una observación/pregunta útil sin inventar",
}
HUMAN_REVIEW_SCALE = {
    "1": "Deficiente: errores graves o respuesta sin sentido",
    "2": "Débil: varios problemas que dificultan seguirla",
    "3": "Adecuada: comprensible y suficientemente correcta",
    "4": "Buena: natural, coherente y bien anclada al hilo",
    "5": "Excelente: natural, precisa y reflexiva sin inventar",
}


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    setup: tuple[tuple[str, str], ...]
    question: str
    required_groups: tuple[tuple[str, ...], ...]
    forbidden: tuple[str, ...] = ()


SCENARIOS = (
    Scenario(
        "old_preference",
        "Recordar una preferencia antigua",
        (("user", "Me encanta el té de jazmín; el café me cae pesado."),
         ("assistant", "Entendido, gracias por contármelo.")),
        "De todo lo que te conté, ¿qué infusión parece gustarme más? ¿Qué podrías preguntarme después sin asumir por qué la prefiero?",
        (("jazmín",),),
    ),
    Scenario(
        "latest_correction",
        "Priorizar una corrección posterior",
        (("user", "Para la reunión pensé que podría ir el martes."),
         ("assistant", "Entendido, por ahora martes."),
         ("user", "Cambio de planes: finalmente puedo ir el jueves, no el martes."),
         ("assistant", "Anotado, queda el jueves.")),
        "¿Cómo resumirías el plan actualizado y qué detalle convendría confirmar antes de organizarse? No des por cierto nada que no te haya contado.",
        (("jueves",),),
        ("martes",),
    ),
    Scenario(
        "project_constraints",
        "Recuperar objetivo y restricción de un proyecto",
        (("user", "Estoy haciendo un juego pequeño de exploración."),
         ("assistant", "Suena bien, cuéntame más."),
         ("user", "Lo estoy desarrollando en Godot y quiero que sea acogedor, sin terror."),
         ("assistant", "Entiendo el estilo que buscas.")),
        "¿Qué experiencia parece que busco para mi juego? Relaciona la exploración acogedora con lo que quiero evitar y sugiere una pregunta para concretar el tono.",
        (
            ("acogedor", "cálido", "tranquilo", "pacífico", "seguro", "segura", "calma", "sereno"),
            ("terror", "miedo", "amenaza", "amenazante", "tensión", "sombras"),
        ),
    ),
    Scenario(
        "topic_return",
        "Volver a un tema después de una digresión",
        (("user", "Mi gato se llama Nube y le gusta dormir junto a la ventana."),
         ("assistant", "Qué nombre tan bonito.")),
        "Volviendo a lo que te conté al principio, ¿qué recuerdas de Nube y qué le preguntarías para seguir la conversación sin inventar detalles?",
        (("nube",), ("ventana",)),
    ),
    Scenario(
        "two_facts",
        "Combinar dos datos del hilo",
        (("user", "El sábado llego en tren a las seis y veinte."),
         ("assistant", "Perfecto."),
         ("user", "Quedamos en el Café Azul a las seis y cuarenta y cinco."),
         ("assistant", "Genial, queda anotado.")),
        "Ayúdame a revisar el plan: distingue a qué hora llego, dónde quedamos y qué hora corresponde al encuentro. Si algo no encaja, señálalo en vez de adivinar.",
        (("6:20", "seis y veinte", "seis veinte", "18:20"),
         ("café azul",)),
        ("6:15", "18:15", "seis y cuarto", "seis cuarto"),
    ),
)

NOISE_TURNS = (
    ("user", "También estoy pensando en ordenar un poco mi escritorio."),
    ("assistant", "Podrías empezar por guardar lo que no uses."),
    ("user", "Ayer vi una película de comedia bastante divertida."),
    ("assistant", "¿Te gustan más las comedias o las de aventuras?"),
    ("user", "Tengo que comprar fruta y pan cuando salga."),
    ("assistant", "Ojalá encuentres todo lo que necesitas."),
    ("user", "Esta semana el clima ha estado cambiante."),
    ("assistant", "Sí, mejor salir con una chaqueta por si acaso."),
)


def build_history(scenario: Scenario, depth: int) -> list[dict[str, str]]:
    """Intercala distractores inocuos para variar la distancia al dato clave."""
    if depth < 0:
        raise ValueError("La profundidad no puede ser negativa")
    history = [
        {"role": role, "content": content} for role, content in scenario.setup
    ]
    noise = [
        {"role": role, "content": content}
        for index in range(depth)
        for role, content in (NOISE_TURNS[index % len(NOISE_TURNS)],)
    ]
    # Los distractores van después de los hechos, para aumentar su distancia a
    # la pregunta sin cambiar la respuesta correcta ni reescribir los datos.
    return [*history, *noise]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


def evaluate_reply(scenario: Scenario, reply: str) -> dict:
    normalized = _normalize(reply)
    missing = [
        list(group) for group in scenario.required_groups
        if not any(_normalize(term) in normalized for term in group)
    ]
    forbidden = [term for term in scenario.forbidden if _normalize(term) in normalized]
    return {
        "passed_anchors": not missing and not forbidden,
        "missing_anchor_groups": missing,
        "forbidden_terms_found": forbidden,
        "manual_review_required": True,
    }


def review_samples_blind(
    samples: list[dict], *, input_fn=input, output_fn=print,
    shuffle_fn=random.shuffle,
) -> None:
    """Pide puntuación humana sin mostrar el presupuesto de cada muestra."""
    ordered = list(samples)
    shuffle_fn(ordered)
    for ordinal, sample in enumerate(ordered, start=1):
        output_fn(
            f"\nMuestra ciega R-{ordinal:03d} — {sample['scenario_label']} "
            f"(hilo con {sample['depth']} mensajes distractores)\n"
            f"Respuesta:\n{sample['answer']}"
        )
        ratings = {}
        for dimension in HUMAN_REVIEW_DIMENSIONS:
            output_fn(
                f"{HUMAN_REVIEW_LABELS[dimension]}: "
                + "; ".join(f"{key}={value}" for key, value in HUMAN_REVIEW_SCALE.items())
            )
            while True:
                value = input_fn("Puntuación (1-5): ").strip()
                if value in HUMAN_REVIEW_SCALE:
                    ratings[dimension] = int(value)
                    break
                output_fn("Introduce un entero del 1 al 5.")
        sample["human_review"] = {
            "ratings": ratings,
            "passed": all(score >= 3 for score in ratings.values())
            and sample["quality"]["passed_anchors"],
        }


def _median(values: list[int | float]) -> int | float | None:
    return statistics.median(values) if values else None


def build_report(rows: list[dict], *, min_pass_rate: float) -> dict:
    budgets = sorted({row["budget"] for row in rows})
    budget_summaries = {}
    for budget in budgets:
        selected = [row for row in rows if row["budget"] == budget]
        by_depth = {}
        for depth in sorted({row["depth"] for row in selected}):
            depth_rows = [row for row in selected if row["depth"] == depth]
            by_depth[str(depth)] = {
                "samples": len(depth_rows),
                "anchor_pass_rate": sum(r["quality"]["passed_anchors"] for r in depth_rows)
                / len(depth_rows),
            }
        budget_summaries[str(budget)] = {
            "samples": len(selected),
            "anchor_pass_rate": sum(r["quality"]["passed_anchors"] for r in selected)
            / len(selected),
            "median_latency_ms": _median([r["latency_ms"] for r in selected]),
            "median_prompt_tokens": _median([
                r["prompt_tokens"] for r in selected if r["prompt_tokens"] is not None
            ]),
            "median_completion_tokens": _median([
                r["completion_tokens"] for r in selected
                if r["completion_tokens"] is not None
            ]),
            "median_observed_reasoning_tokens": _median([
                r["reasoning_tokens"] for r in selected
                if r["reasoning_tokens"] is not None
            ]),
            "truncated_samples": sum(r["finish_reason"] == "length" for r in selected),
            "by_context_depth": by_depth,
        }

    eligible = []
    anchor_eligible = []
    for budget in budgets:
        summary = budget_summaries[str(budget)]
        anchor_passes_depths = not any(
            depth_summary["anchor_pass_rate"] < min_pass_rate
            for depth_summary in summary["by_context_depth"].values()
        )
        if summary["anchor_pass_rate"] >= min_pass_rate and anchor_passes_depths:
            anchor_eligible.append(budget)

        selected = [row for row in rows if row["budget"] == budget]
        reviewed = [row for row in selected if isinstance(row.get("human_review"), dict)]
        human_pass_rate = (
            sum(bool(row["human_review"].get("passed")) for row in reviewed) / len(reviewed)
            if reviewed else None
        )
        summary["human_review"] = {
            "reviewed_samples": len(reviewed),
            "total_samples": len(selected),
            "pass_rate": human_pass_rate,
            "by_context_depth": {
                depth: {
                    "reviewed_samples": len(depth_rows := [
                        row for row in reviewed if str(row["depth"]) == depth
                    ]),
                    "pass_rate": (
                        sum(bool(row["human_review"].get("passed")) for row in depth_rows)
                        / len(depth_rows)
                        if depth_rows else None
                    ),
                }
                for depth in summary["by_context_depth"]
            },
            "median_by_dimension": {
                dimension: _median([
                    row["human_review"]["ratings"][dimension]
                    for row in reviewed
                    if dimension in row["human_review"].get("ratings", {})
                ])
                for dimension in HUMAN_REVIEW_DIMENSIONS
            },
        }
        all_rows_reviewed = len(reviewed) == len(selected) and bool(selected)
        if (
            all_rows_reviewed
            and summary["anchor_pass_rate"] >= min_pass_rate
            and human_pass_rate is not None
            and human_pass_rate >= min_pass_rate
            and anchor_passes_depths
            and all(
                depth_summary["pass_rate"] is not None
                and depth_summary["pass_rate"] >= min_pass_rate
                for depth_summary in summary["human_review"]["by_context_depth"].values()
            )
        ):
            eligible.append(budget)
    any_review = any(row.get("human_review") for row in rows)
    all_reviewed = all(
        isinstance(row.get("human_review"), dict)
        for row in rows
    )
    return {
        "suite": "airi_synthetic_conversation_reasoning_sweep_v2",
        "mode": "auto_with_per_call_reasoning_override",
        "min_anchor_pass_rate": min_pass_rate,
        "candidate_sweet_spot_tokens": min(eligible) if eligible else None,
        "anchor_only_candidate_tokens": min(anchor_eligible) if anchor_eligible else None,
        "decision_status": (
            "human_review_complete" if eligible
            else "no_budget_passed" if any_review and all_reviewed
            else "requires_blind_human_review"
        ),
        "sweet_spot_rule": (
            "Menor presupuesto que pasa los anchors y la revisión humana ciega "
            "(todas las dimensiones >= 3/5) globalmente y por profundidad."
        ),
        "manual_review_rubric": {
            "dimensions": list(HUMAN_REVIEW_DIMENSIONS),
            "scale": HUMAN_REVIEW_SCALE,
            "blind_to_budget": True,
            "score_anchor": "No puntúes más alto por una respuesta larga; penaliza inferencias presentadas como hechos.",
        },
        "limitations": [
            "Los anchors léxicos son un filtro de hechos críticos, no evalúan gramática, naturalidad ni calidad reflexiva.",
            "Una muestra por escenario/presupuesto es exploratoria; repetir para medir variabilidad.",
            "Los distractores sintéticos no representan toda la distribución de conversaciones reales.",
            "prompt_tokens refleja lo informado por el servidor, si está disponible.",
            "No se guardan prompts completos ni contexto; las respuestas del reporte derivan de entradas sintéticas.",
            "La revisión semántica de conversación se desactiva en este runner para aislar la llamada primaria.",
        ],
        "budget_summaries": budget_summaries,
        "samples": rows,
    }


async def _run_one(llm, scenario: Scenario, depth: int, budget: int, repeat: int) -> dict:
    state, _ = make_state()
    state.histories[0] = build_history(scenario, depth)
    history_message_count = len(state.histories[0]) + 1
    service = ConversationService(llm=llm, state=state, search=None, gifs=None, notifier=None)
    # Este runner mide la generación primaria; evita una segunda llamada del
    # revisor semántico que confundiría el presupuesto probado.
    service.conversation_review_enabled = False
    context = TurnContext(
        allow_web=False,
        correlation_id=f"reasoning-sweep-{scenario.key}-{depth}-{budget}-{repeat}",
        stream_llm=True,
        llm_reasoning_budget_tokens=budget,
    )
    started = time.perf_counter()
    result = await service.run_turn(USER, [(USER, scenario.question)], context)
    latency_ms = int((time.perf_counter() - started) * 1000)
    trace = result.trace
    calls = trace.llm_calls if trace is not None else []
    primary = next((call for call in calls if call.get("purpose") == "primary"), {})
    reply = result.reply or ""
    quality = evaluate_reply(scenario, reply)
    return {
        "scenario": scenario.key,
        "scenario_label": scenario.label,
        "depth": depth,
        "history_messages": history_message_count,
        "budget": budget,
        "repeat": repeat,
        "answer": reply,
        "expected_anchor_groups": [list(group) for group in scenario.required_groups],
        "quality": quality,
        "latency_ms": latency_ms,
        "prompt_tokens": (primary.get("usage") or {}).get("prompt_tokens"),
        "completion_tokens": (primary.get("usage") or {}).get("completion_tokens"),
        "reasoning_tokens": primary.get("reasoning_tokens"),
        "effective_reasoning_budget_tokens": primary.get("reasoning_budget_tokens"),
        "finish_reason": primary.get("finish_reason"),
        "call_count": len(calls),
        "repair_calls": sum(call.get("purpose") != "primary" for call in calls),
    }


async def run_sweep(
    llm, *, budgets: tuple[int, ...], depths: tuple[int, ...], repeats: int,
    scenario_keys: tuple[str, ...] | None = None,
    on_sample: Callable[[dict], None] | None = None,
) -> list[dict]:
    if getattr(llm, "provider", None) != "llama":
        raise ValueError("El barrido requiere LLM_PROVIDER=llama para medir thinking_budget_tokens")
    scenarios = [s for s in SCENARIOS if scenario_keys is None or s.key in scenario_keys]
    if not scenarios:
        raise ValueError("No hay escenarios seleccionados")
    rows = []
    for scenario in scenarios:
        for depth in depths:
            for budget in budgets:
                for repeat in range(1, repeats + 1):
                    row = await _run_one(llm, scenario, depth, budget, repeat)
                    rows.append(row)
                    if on_sample is not None:
                        on_sample(row)
    return rows


def _csv_ints(raw: str, *, label: str, allow_zero: bool = False) -> tuple[int, ...]:
    try:
        values = tuple(dict.fromkeys(int(part.strip()) for part in raw.split(",")))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} debe ser una lista separada por comas") from exc
    minimum = 0 if allow_zero else 1
    if not values or any(value < minimum for value in values):
        qualifier = "no negativos" if allow_zero else "positivos"
        raise argparse.ArgumentTypeError(f"{label} requiere enteros {qualifier}")
    return values


async def _run_cli(args) -> dict:
    os.environ["LLM_THINKING_MODE"] = "auto"
    checkpoint_path = (
        args.out.with_suffix(args.out.suffix + ".partial.jsonl")
        if args.out else None
    )
    if checkpoint_path:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text("", encoding="utf-8")

    def checkpoint(row):
        if checkpoint_path:
            with checkpoint_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    async with aiohttp.ClientSession() as session:
        llm = build_llm(session)
        if llm.provider != "llama":
            raise ValueError("Configura LLM_PROVIDER=llama; otros proveedores ignoran este presupuesto")
        rows = await run_sweep(
            llm,
            budgets=args.budgets,
            depths=args.depths,
            repeats=args.repeats,
            scenario_keys=args.scenario or None,
            on_sample=checkpoint,
        )
    report = build_report(rows, min_pass_rate=args.min_pass_rate)
    report["checkpoint_jsonl"] = str(checkpoint_path) if checkpoint_path else None
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Evalúa presupuestos de reasoning de Airi con hilos sintéticos y el modelo local."
    )
    parser.add_argument("--budgets", type=lambda v: _csv_ints(v, label="budgets"),
                        default=DEFAULT_BUDGETS)
    parser.add_argument("--depths", type=lambda v: _csv_ints(v, label="depths", allow_zero=True),
                        default=DEPTHS,
                        help="cantidad de mensajes distractores al final del hilo")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--scenario", action="append", choices=[s.key for s in SCENARIOS])
    parser.add_argument("--min-pass-rate", type=float, default=DEFAULT_MIN_PASS_RATE)
    parser.add_argument("--review", action="store_true",
                        help="puntuar respuestas a ciegas por español, coherencia, fidelidad, pertinencia y reflexión")
    parser.add_argument("--out", type=Path, help="guardar reporte JSON (incluye respuestas sintéticas)")
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats debe ser al menos 1")
    if not 0 < args.min_pass_rate <= 1:
        parser.error("--min-pass-rate debe estar en (0, 1]")
    try:
        report = asyncio.run(_run_cli(args))
        if args.review:
            review_samples_blind(report["samples"])
            report = build_report(report["samples"], min_pass_rate=args.min_pass_rate)
            report["checkpoint_jsonl"] = str(
                args.out.with_suffix(args.out.suffix + ".partial.jsonl")
            ) if args.out else None
    except Exception as exc:
        print(f"ERROR reasoning sweep: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(f"Reporte guardado: {args.out}")
        print(f"Punto dulce candidato: {report['candidate_sweet_spot_tokens']}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
