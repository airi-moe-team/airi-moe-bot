"""Validación de borradores de turno frente al estado actual (tarea 1.3)."""

from __future__ import annotations

from airi.domain.turn_guard import (
    DateFingerprint,
    GuardDecision,
    fingerprint_of,
    validate_turn,
)


def session(scene="playa", started_at=10.0, state="active"):
    return {"scene": scene, "started_at": started_at, "state": state}


def test_fingerprint_uses_scene_and_start():
    assert fingerprint_of(session()) == DateFingerprint("playa", 10.0)


def test_fingerprint_is_none_without_active_session():
    assert fingerprint_of(None) is None
    assert fingerprint_of({}) is None
    assert fingerprint_of(session(state="closed")) is None


def test_fingerprint_tolerates_bad_start_value():
    assert fingerprint_of(session(started_at="no")) == DateFingerprint("playa", 0.0)


def test_valid_turn_outside_a_date():
    assert validate_turn(
        draft_season=1,
        draft_date=None,
        current_season=1,
        current_date=None,
    ) is GuardDecision.VALID


def test_valid_turn_inside_the_same_date():
    fingerprint = fingerprint_of(session())
    assert validate_turn(
        draft_season=1,
        draft_date=fingerprint,
        current_season=1,
        current_date=session(),
    ) is GuardDecision.VALID


def test_replaced_date_is_stale():
    fingerprint = fingerprint_of(session(scene="playa"))
    assert validate_turn(
        draft_season=1,
        draft_date=fingerprint,
        current_season=1,
        current_date=session(scene="cine"),
    ) is GuardDecision.STALE_DATE


def test_closed_date_is_stale():
    fingerprint = fingerprint_of(session())
    assert validate_turn(
        draft_season=1,
        draft_date=fingerprint,
        current_season=1,
        current_date=None,
    ) is GuardDecision.STALE_DATE


def test_date_started_during_generation_is_stale():
    assert validate_turn(
        draft_season=1,
        draft_date=None,
        current_season=1,
        current_date=session(),
    ) is GuardDecision.STALE_DATE


def test_changed_season_is_stale():
    assert validate_turn(
        draft_season=1,
        draft_date=None,
        current_season=2,
        current_date=None,
    ) is GuardDecision.STALE_SEASON
