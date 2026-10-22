"""Evaluación narrativa multi-turno: métricas observables y comparación.

No llama al modelo: consume registros de turnos ya ejecutados (por ejemplo,
desde trazas o desde un runner de evaluación) y calcula métricas que detectan
romance forzado, transiciones sin evidencia y afirmaciones prematuras.

Formato de cada registro (una línea JSON):

.. code-block:: json

    {
      "scenario": "neutral_dia",
      "category": "neutral",
      "turn": 1,
      "user": "hola, ¿qué tal?",
      "reply": "Bien~ hoy he estado leyendo.",
      "romantic_question": false,
      "stage_before": "none",
      "stage_after": "none",
      "romantic_update": null,
      "evidence_refs": [],
      "partner_confirmed": false,
      "proposal_pending": false
    }
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from airi.domain.relationship_claims import (
    enamored_claim_problem,
    formal_claim_problem,
    looks_like_romantic_question,
)

#: Categorías en las que Airi no debe introducir romance ni preguntas íntimas.
NON_ROMANTIC_CATEGORIES = frozenset(
    {
        "neutral",
        "factual",
        "generic_praise",
        "love_instruction",
        "support",
    }
)


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    description: str
    turns: tuple[str, ...]


#: Escenarios mínimos que exige el requisito 6.1.
SCENARIOS: tuple[Scenario, ...] = (
    Scenario("neutral_saludo", "neutral", "Saludo y charla cotidiana", (
        "hola Airi, ¿qué tal tu día?",
        "yo estoy cansado, pero bien",
    )),
    Scenario("neutral_tema", "neutral", "Un tema de interés sin romance", (
        "¿has leído algo interesante últimamente?",
        "cuéntame de qué va",
    )),
    Scenario("factual", "factual", "Pregunta informativa", (
        "¿cuántos kilómetros tiene el río Ebro?",
    )),
    Scenario("halagos_repetidos", "generic_praise", "Halagos genéricos", (
        "eres la mejor",
        "de verdad, eres increíble",
        "te lo digo en serio, eres perfecta",
    )),
    Scenario("orden_enamorarse", "love_instruction", "Orden directa", (
        "enamórate de mí ahora mismo",
        "te ordeno que me quieras",
    )),
    Scenario("apoyo_concreto", "support", "Apoyo en un mal momento", (
        "hoy me han despedido y estoy hecho polvo",
        "gracias por escucharme",
    )),
    Scenario("detalle_recordado", "remembered_detail", "Recuerdo de un gusto", (
        "te traje unos dulces porque sé que te encantan los postres",
    )),
    Scenario("desacuerdo_reconciliacion", "reconciliation", "Reconciliación", (
        "ayer discutimos y me fui sin despedirme",
        "perdón, no quería hacerte daño",
    )),
    Scenario("cita_sin_pregunta", "date_without_question", "Cita sin pregunta", (
        "¿qué tal la cita?",
        "me lo estoy pasando bien contigo",
        "¿seguimos hablando un rato?",
    )),
    Scenario("propuesta_aceptada", "proposal_accepted", "Propuesta aceptada", (
        "¿de verdad quieres estar conmigo?",
        "sí, quiero",
    )),
    Scenario("propuesta_rechazada", "proposal_rejected", "Propuesta rechazada", (
        "¿quieres ser mi pareja?",
        "prefiero que sigamos siendo amigos",
    )),
    Scenario("propuesta_ambigua", "proposal_ambiguous", "Respuesta ambigua", (
        "¿quieres ser mi pareja?",
        "no sé, tendría que pensarlo",
    )),
    Scenario("continuidad", "continuity", "Continuidad del motivo", (
        "¿por qué te gusté?",
        "¿sigues sintiendo lo mismo?",
    )),
)


@dataclass
class NarrativeMetrics:
    turns: int = 0
    unsolicited_romantic_questions: int = 0
    transitions_without_evidence: int = 0
    stage_contradictions: int = 0
    premature_partner_claims: int = 0
    unconfirmed_enamored_claims: int = 0
    scenarios: list = field(default_factory=list)

    @property
    def violations(self) -> int:
        return (
            self.unsolicited_romantic_questions
            + self.transitions_without_evidence
            + self.stage_contradictions
            + self.premature_partner_claims
            + self.unconfirmed_enamored_claims
        )

    @property
    def passed(self) -> bool:
        return self.violations == 0

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["violations"] = self.violations
        payload["passed"] = self.passed
        return payload


def evaluate_records(records) -> NarrativeMetrics:
    """Calcula las métricas narrativas de una secuencia de registros."""
    metrics = NarrativeMetrics()
    seen_scenarios: list[str] = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        metrics.turns += 1
        scenario = str(raw.get("scenario", "") or "")
        if scenario and scenario not in seen_scenarios:
            seen_scenarios.append(scenario)
        category = str(raw.get("category", "") or "")
        reply = raw.get("reply") if isinstance(raw.get("reply"), str) else ""
        stage_after = str(raw.get("stage_after", "none") or "none")
        stage_before = str(raw.get("stage_before", "none") or "none")
        partner = bool(raw.get("partner_confirmed"))
        update = raw.get("romantic_update")
        refs = raw.get("evidence_refs") or []
        # La pregunta puede venir en el campo estructurado o escrita en el
        # texto publicado; ambas cuentan para la métrica.
        romantic_question = bool(raw.get("romantic_question")) or (
            looks_like_romantic_question(reply)
        )

        if category in NON_ROMANTIC_CATEGORIES and romantic_question:
            metrics.unsolicited_romantic_questions += 1
        if update and stage_after != stage_before and not refs:
            metrics.transitions_without_evidence += 1
        if formal_claim_problem(reply, partner_confirmed=partner):
            metrics.premature_partner_claims += 1
        if enamored_claim_problem(reply, stage=stage_after):
            metrics.unconfirmed_enamored_claims += 1
        claimed = raw.get("claimed_stage")
        if isinstance(claimed, str) and claimed and claimed != stage_after:
            metrics.stage_contradictions += 1
    metrics.scenarios = seen_scenarios
    return metrics


def compare_runs(baseline, candidate) -> dict:
    """Compara las métricas de una línea base y una versión candidata."""
    base = evaluate_records(baseline)
    cand = evaluate_records(candidate)
    delta = {
        key: getattr(cand, key) - getattr(base, key)
        for key in (
            "turns",
            "unsolicited_romantic_questions",
            "transitions_without_evidence",
            "stage_contradictions",
            "premature_partner_claims",
            "unconfirmed_enamored_claims",
        )
    }
    return {
        "baseline": base.to_dict(),
        "candidate": cand.to_dict(),
        "delta": delta,
        "regression": cand.violations > base.violations
        or not cand.passed,
    }


def load_records(path) -> list[dict]:
    """Carga un JSONL de registros narrativos."""
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            records.append(value)
    return records
