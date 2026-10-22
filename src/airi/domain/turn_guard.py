"""Decide si un borrador generado sigue siendo aplicable (dominio puro)."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import NamedTuple

from airi.domain.relationships import RelationshipFingerprint

_ACTIVE_DATE_STATES = {"active", "last_chance", "final_scene"}


class GuardDecision(str, Enum):
    VALID = "valid"
    STALE_DATE = "stale_date"
    STALE_SEASON = "stale_season"
    STALE_RELATIONSHIP = "stale_relationship"


class DateFingerprint(NamedTuple):
    """Identidad estable de una sesión de cita sin añadir campos al esquema."""

    scene: str
    started_at: float


def fingerprint_of(session: Mapping[str, object] | None) -> DateFingerprint | None:
    """Huella de la cita vigente, o None si no hay cita abierta."""
    if not isinstance(session, Mapping):
        return None
    raw_state = session.get("state")
    if not raw_state or str(raw_state) not in _ACTIVE_DATE_STATES:
        return None
    scene = str(session.get("scene") or "")
    try:
        started_at = float(session.get("started_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        started_at = 0.0
    return DateFingerprint(scene, started_at)


def validate_turn(
    *,
    draft_season: int,
    draft_date: DateFingerprint | None,
    current_season: int,
    current_date: Mapping[str, object] | None,
    draft_relationship: RelationshipFingerprint | None = None,
    current_relationship: RelationshipFingerprint | None = None,
) -> GuardDecision:
    """Compara el borrador con el estado actual sin mutarlo."""
    if int(draft_season) != int(current_season):
        return GuardDecision.STALE_SEASON

    current = fingerprint_of(current_date)
    if draft_date is None:
        if current is not None:
            return GuardDecision.STALE_DATE
    elif current is None or current != draft_date:
        return GuardDecision.STALE_DATE

    if (
        draft_relationship is not None
        and current_relationship is not None
        and draft_relationship != current_relationship
    ):
        return GuardDecision.STALE_RELATIONSHIP
    return GuardDecision.VALID
