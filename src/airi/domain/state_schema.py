"""Esquema puro del estado canónico y de los conjuntos heredados.

La validación ocurre antes de que un agregado se convierta en estado activo o
antes de que una migración lo active. No hay I/O en este módulo: recibe datos
ya parseados y devuelve errores legibles para el operador.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    return ValidationResult(True, ())


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
