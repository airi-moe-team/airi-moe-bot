"""Módulo de evaluación de calidad narrativa de Airi."""

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
    "NON_ROMANTIC_CATEGORIES",
    "SCENARIOS",
    "NarrativeMetrics",
    "Scenario",
    "compare_runs",
    "evaluate_records",
    "load_records",
    "run_scenario",
]
