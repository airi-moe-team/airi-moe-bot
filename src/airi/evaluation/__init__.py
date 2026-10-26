"""Módulo de evaluación de calidad narrativa de Airi."""

from airi.evaluation.interaction import (
    EVAL_NOW,
    INTERACTION_SCENARIOS,
    RUBRIC_CRITERIA,
    RUBRIC_MAX_TOTAL,
    EvalUser,
    InteractionMetrics,
    InteractionScenario,
    compare_interactions,
    evaluate_interactions,
    generate_live_records,
    load_records as load_interaction_records,
    write_records,
)
from airi.evaluation.narrative import (
    NON_ROMANTIC_CATEGORIES,
    SCENARIOS,
    NarrativeMetrics,
    Scenario,
    compare_runs,
    evaluate_records,
    load_records,
)
from airi.evaluation.runner import run_scenario

__all__ = [
    "EVAL_NOW",
    "INTERACTION_SCENARIOS",
    "NON_ROMANTIC_CATEGORIES",
    "RUBRIC_CRITERIA",
    "RUBRIC_MAX_TOTAL",
    "SCENARIOS",
    "EvalUser",
    "InteractionMetrics",
    "InteractionScenario",
    "NarrativeMetrics",
    "Scenario",
    "compare_interactions",
    "compare_runs",
    "evaluate_interactions",
    "evaluate_records",
    "generate_live_records",
    "load_interaction_records",
    "load_records",
    "run_scenario",
    "write_records",
]
