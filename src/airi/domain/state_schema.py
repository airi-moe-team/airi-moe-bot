"""Esquema puro del estado canónico y de los conjuntos heredados.

La validación ocurre antes de que un agregado se convierta en estado activo o
antes de que una migración lo active. No hay I/O en este módulo: recibe datos
ya parseados y devuelve errores legibles para el operador.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from airi.domain.relationships import EVIDENCE_KINDS, ROMANTIC_STAGES

CURRENT_SCHEMA_VERSION = 1

#: Claves obligatorias del agregado y su tipo esperado.
REQUIRED_STATE_KEYS: dict[str, type | tuple[type, ...]] = {
    "schema_version": int,
    "state_version": int,
    "world": dict,
    "affinity": dict,
    "dates": dict,
    "memories": dict,
    "diary": list,
    "users": dict,
    "histories": dict,
    "turn_records": dict,
    "message_index": dict,
}

#: Claves opcionales del agregado.
OPTIONAL_STATE_KEYS: dict[str, type | tuple[type, ...]] = {
    "archive": dict,
}

#: Tipo esperado de cada fichero JSON heredado.
LEGACY_DATASETS: dict[str, type | tuple[type, ...]] = {
    "world": dict,
    "affinity": dict,
    "dates": dict,
    "diary": list,
    "memories": dict,
    "users": dict,
}

OPTIONAL_LEGACY_DATASETS: dict[str, type | tuple[type, ...]] = {
    "histories": dict,
}


@dataclass(frozen=True)
class ValidationResult:
    """Resultado de validar un agregado o un conjunto heredado."""

    ok: bool
    errors: tuple[str, ...] = ()


def validate_state(data: object) -> ValidationResult:
    """Valida el agregado canónico completo."""
    if not isinstance(data, dict):
        return ValidationResult(False, ("estado: la raíz debe ser un objeto",))

    errors: list[str] = []
    _check_keys(data, REQUIRED_STATE_KEYS, errors, "estado", required=True)
    _check_keys(data, OPTIONAL_STATE_KEYS, errors, "estado", required=False)

    raw_version = data.get("schema_version")
    if _is_int(raw_version) and raw_version > CURRENT_SCHEMA_VERSION:
        errors.append(
            f"estado: schema_version {raw_version} es más nueva que la "
            f"soportada ({CURRENT_SCHEMA_VERSION})"
        )

    world = data.get("world")
    if isinstance(world, dict):
        _validate_world(world, errors, "estado.world")

    return ValidationResult(not errors, tuple(errors))


def validate_legacy_dataset(name: str, data: object) -> ValidationResult:
    """Valida uno de los ficheros JSON heredados por su nombre lógico."""
    expected = LEGACY_DATASETS.get(name)
    optional = False
    if expected is None:
        expected = OPTIONAL_LEGACY_DATASETS.get(name)
        optional = expected is not None
    if expected is None:
        return ValidationResult(False, (f"heredado: conjunto desconocido '{name}'",))
    if data is None and optional:
        return ValidationResult(False, (f"heredado {name}: no puede ser nulo",))

    expected_types = expected if isinstance(expected, tuple) else (expected,)
    if not isinstance(data, expected_types) or isinstance(data, bool):
        names = "/".join(t.__name__ for t in expected_types)
        return ValidationResult(
            False, (f"heredado {name}: se esperaba {names}",)
        )
    if name == "world":
        errors: list[str] = []
        _validate_world(data, errors, "heredado world")
        if errors:
            return ValidationResult(False, tuple(errors))
    return ValidationResult(True, ())


def _validate_world(world: dict, errors: list[str], label: str) -> None:
    """Valida el estado romántico anidado dentro de `world`."""
    mood = world.get("mood")
    if mood is not None and not isinstance(mood, dict):
        errors.append(f"{label}.mood debe ser dict o nulo")
    mood_history = world.get("mood_history", [])
    if not isinstance(mood_history, list):
        errors.append(f"{label}.mood_history debe ser una lista")
    if "relationships" not in world:
        return
    relationships = world.get("relationships")
    if not isinstance(relationships, dict):
        errors.append(f"{label}.relationships debe ser dict")
        return
    for uid, record in relationships.items():
        where = f"{label}.relationships[{uid}]"
        if not isinstance(record, dict):
            errors.append(f"{where} debe ser un objeto")
            continue
        stage = record.get("stage", "none")
        if stage not in ROMANTIC_STAGES:
            errors.append(f"{where}.stage no es una etapa válida")
        history = record.get("history", [])
        if not isinstance(history, list):
            errors.append(f"{where}.history debe ser una lista")
            history = []
        for index, entry in enumerate(history):
            _validate_history_entry(entry, errors, f"{where}.history[{index}]")
        pending = record.get("pending_proposal")
        if pending is not None:
            _validate_pending(pending, errors, f"{where}.pending_proposal")
    winner = world.get("winner_id")
    if winner is not None and not isinstance(winner, (str, int)):
        errors.append(f"{label}.winner_id debe ser texto o entero")


def _validate_history_entry(entry: object, errors: list[str], where: str) -> None:
    if not isinstance(entry, dict):
        errors.append(f"{where} debe ser un objeto")
        return
    if entry.get("from") not in ROMANTIC_STAGES:
        errors.append(f"{where}.from no es una etapa válida")
    if entry.get("to") not in ROMANTIC_STAGES:
        errors.append(f"{where}.to no es una etapa válida")
    kind = entry.get("evidence_kind")
    if kind not in EVIDENCE_KINDS and kind != "legacy":
        errors.append(f"{where}.evidence_kind no es válida")
    if not _is_nonempty_str(entry.get("reason")):
        errors.append(f"{where}.reason no puede estar vacío")
    if not isinstance(entry.get("evidence_refs"), list):
        errors.append(f"{where}.evidence_refs debe ser una lista")
    if "evidence_summary" in entry and not isinstance(
        entry.get("evidence_summary"), str
    ):
        errors.append(f"{where}.evidence_summary debe ser texto")


def _validate_pending(pending: object, errors: list[str], where: str) -> None:
    if not isinstance(pending, dict):
        errors.append(f"{where} debe ser un objeto o null")
        return
    if not _is_nonempty_str(pending.get("target_user_id")):
        errors.append(f"{where}.target_user_id no puede estar vacío")
    refs = pending.get("evidence_refs", [])
    if refs is not None and not isinstance(refs, list):
        errors.append(f"{where}.evidence_refs debe ser una lista")


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_keys(
    data: dict[str, Any],
    schema: dict[str, type | tuple[type, ...]],
    errors: list[str],
    label: str,
    *,
    required: bool,
) -> None:
    for key, expected in schema.items():
        if key not in data:
            if required:
                errors.append(f"{label}: falta la clave obligatoria '{key}'")
            continue
        value = data[key]
        expected_types = expected if isinstance(expected, tuple) else (expected,)
        if not isinstance(value, expected_types) or (
            isinstance(value, bool) and int in expected_types
        ):
            names = "/".join(t.__name__ for t in expected_types)
            errors.append(f"{label}: '{key}' debe ser {names}")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
