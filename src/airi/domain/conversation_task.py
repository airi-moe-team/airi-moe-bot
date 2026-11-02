"""Normalización segura del resumen efímero de una tarea conversacional."""

from __future__ import annotations

TASK_CONTEXT_ACTIONS = {"none", "set", "clear"}
MAX_GOAL_CHARS = 240
MAX_CONSTRAINTS = 5
MAX_CONSTRAINT_CHARS = 120
MAX_PROGRESS_CHARS = 180
MAX_NEXT_STEP_CHARS = 180


def _clean_text(value, limit):
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    return text[:limit]


def normalize_task_context_update(raw):
    """Valida y limita el update propuesto por el LLM; inválido significa noop."""
    noop = {
        "action": "none",
        "goal": "",
        "constraints": [],
        "progress": "",
        "next_step": "",
    }
    if not isinstance(raw, dict):
        return noop
    action = raw.get("action")
    if action not in TASK_CONTEXT_ACTIONS:
        return noop
    if action == "none":
        return noop
    if action == "clear":
        return {**noop, "action": "clear"}

    goal = _clean_text(raw.get("goal"), MAX_GOAL_CHARS)
    constraints = raw.get("constraints")
    if not goal or not isinstance(constraints, list):
        return noop
    clean_constraints = []
    for constraint in constraints:
        text = _clean_text(constraint, MAX_CONSTRAINT_CHARS)
        if text and text not in clean_constraints:
            clean_constraints.append(text)
        if len(clean_constraints) >= MAX_CONSTRAINTS:
            break
    return {
        "action": "set",
        "goal": goal,
        "constraints": clean_constraints,
        "progress": _clean_text(raw.get("progress"), MAX_PROGRESS_CHARS),
        "next_step": _clean_text(raw.get("next_step"), MAX_NEXT_STEP_CHARS),
    }
