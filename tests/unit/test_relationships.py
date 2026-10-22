"""Tests del dominio relacional: etapas, evidencia y propuestas de pareja."""

from __future__ import annotations

import copy

import pytest

from airi.domain import relationships as R

NOW = 1_000_000.0
SEASON = 4


def _refs(*items):
    return {str(item) for item in items}


def _record(stage="none", history=None, pending=None):
    return {
        "stage": stage,
        "history": list(history or []),
        "pending_proposal": pending,
    }


def _history_entry(entry_id="r1", **overrides):
    entry = {
        "id": entry_id,
        "from": "curiosity",
        "to": "interest",
        "evidence_kind": "support",
        "reason": "Me apoyó",
        "evidence_refs": ["turn:1:10"],
        "evidence_summary": "Me apoyó cuando estaba triste.",
        "season": SEASON,
        "created_at": NOW,
    }
    entry.update(overrides)
    return entry


def _update(**overrides):
    payload = {
        "stage": "curiosity",
        "evidence_kind": "shared_experience",
        "reason": "Me hizo reír y me escuchó de verdad.",
        "evidence_refs": ["turn:1:10"],
        "evidence_summary": "Hablamos de su día y se acordó de mi gusto por el ramen.",
    }
    payload.update(overrides)
    return R.normalize_update(payload)


# ---------------------------------------------------------------------------
# Normalización y migración
# ---------------------------------------------------------------------------


def test_default_relationship_is_non_romantic():
    record = R.default_relationship()
    assert record["stage"] == "none"
    assert record["history"] == []
    assert record["pending_proposal"] is None


def test_normalize_relationship_tolerates_old_or_broken_records():
    assert R.normalize_relationship(None)["stage"] == "none"
    record = R.normalize_relationship(
        {"stage": "inventada", "history": "no", "pending_proposal": "no"}
    )
    assert record["stage"] == "none"
    assert record["history"] == []
    assert record["pending_proposal"] is None


def test_normalize_relationship_keeps_valid_history_entries():
    entry = {
        "id": "t1",
        "from": "none",
        "to": "curiosity",
        "evidence_kind": "support",
        "reason": "Me apoyó",
        "evidence_refs": ["turn:1:1"],
        "evidence_summary": "Me apoyó cuando estaba triste.",
        "season": SEASON,
        "created_at": NOW,
    }
    record = R.normalize_relationship(_record("curiosity", [entry, {"id": ""}]))
    assert record["stage"] == "curiosity"
    assert len(record["history"]) == 1
    assert record["history"][0]["id"] == "t1"


def test_normalize_world_migrates_existing_partner_without_inventing_evidence():
    world = {
        "winner_id": "42",
        "affinity": {"42": {"points": 100}},
    }
    R.normalize_world(world)
    record = world["relationships"]["42"]
    assert record["stage"] == "enamored"
    assert record["history"] == []
    assert record["pending_proposal"] is None


def test_normalize_world_never_infers_romance_from_affinity():
    world = {
        "winner_id": None,
        "affinity": {"7": {"points": 100}},
        "relationships": {},
    }
    R.normalize_world(world)
    assert world["relationships"] == {}


def test_normalize_world_resets_orphan_stage_without_history():
    world = {
        "winner_id": None,
        "relationships": {"7": {"stage": "enamored", "history": []}},
    }
    R.normalize_world(world)
    assert world["relationships"]["7"]["stage"] == "none"


def test_normalize_world_caps_other_stages_when_there_is_a_partner():
    world = {
        "winner_id": "42",
        "relationships": {
            "9": _record("enamored", [_history_entry()]),
        },
    }
    R.normalize_world(world)
    assert world["relationships"]["9"]["stage"] == "interest"


# ---------------------------------------------------------------------------
# Validación de transiciones
# ---------------------------------------------------------------------------


def test_update_requires_a_single_forward_step():
    record = _record("none")
    decision = R.validate_stage_update(
        record, _update(stage="interest"), allowed_refs=_refs("turn:1:10")
    )
    assert decision.accepted is False
    assert decision.code == "invalid_transition"


@pytest.mark.parametrize("stage", ["none", "inventada"])
def test_update_rejects_the_sentinel_and_unknown_stages(stage):
    decision = R.validate_stage_update(
        _record("none"), _update(stage=stage), allowed_refs=_refs("turn:1:10")
    )
    assert decision.accepted is False


def test_update_requires_reason_kind_and_evidence():
    refs = _refs("turn:1:10")
    assert R.validate_stage_update(
        _record("none"), _update(reason="  "), allowed_refs=refs
    ).code == "missing_reason"
    assert R.validate_stage_update(
        _record("none"),
        R.StageUpdate(
            stage="curiosity",
            evidence_kind="halago",
            reason="me halagó",
            evidence_refs=("turn:1:10",),
            evidence_summary="",
        ),
        allowed_refs=refs,
    ).code == "invalid_evidence_kind"
    assert R.validate_stage_update(
        _record("none"), _update(evidence_refs=[]), allowed_refs=refs
    ).code == "missing_evidence"


def test_update_rejects_references_from_another_person_or_unknown():
    decision = R.validate_stage_update(
        _record("none"),
        _update(evidence_refs=["turn:2:99"]),
        allowed_refs=_refs("turn:1:10"),
    )
    assert decision.accepted is False
    assert decision.code == "unknown_evidence"


def test_valid_update_is_applied_with_a_minimal_summary():
    record = _record("curiosity")
    update = _update(
        stage="interest",
        evidence_kind="remembered_detail",
        evidence_summary="",
    )
    decision = R.validate_stage_update(
        record, update, allowed_refs=_refs("turn:1:10")
    )
    assert decision.accepted is True
    applied = R.apply_update(record, decision, now=NOW, season=SEASON)
    assert record["stage"] == "interest"
    assert applied["from"] == "curiosity"
    assert applied["to"] == "interest"
    assert applied["evidence_summary"]  # cae al motivo, nunca queda vacío
    assert applied["season"] == SEASON
    assert record["history"][0]["id"] == applied["id"]


def test_update_from_none_to_curiosity_is_allowed_with_evidence():
    decision = R.validate_stage_update(
        _record("none"), _update(), allowed_refs=_refs("turn:1:10")
    )
    assert decision.accepted is True
    assert decision.to_stage == "curiosity"


# ---------------------------------------------------------------------------
# Propuestas y aceptación
# ---------------------------------------------------------------------------


def _propose(**overrides):
    payload = {
        "action": "propose",
        "reason": "Quiero estar con esta persona.",
        "evidence_refs": ["turn:1:20"],
    }
    payload.update(overrides)
    return R.normalize_action(payload)


def test_propose_requires_enamored_stage_before_the_turn():
    record = _record("interest")
    decision = R.validate_action(
        record,
        _propose(),
        actor_id="42",
        allowed_refs=_refs("turn:1:20"),
        stage_before="interest",
        has_partner=False,
    )
    assert decision.accepted is False
    assert decision.code == "stage_not_confirmed"


def test_propose_cannot_be_combined_with_the_transition_to_enamored():
    record = _record("enamored")
    decision = R.validate_action(
        record,
        _propose(),
        actor_id="42",
        allowed_refs=_refs("turn:1:20"),
        stage_before="interest",
        has_partner=False,
    )
    assert decision.accepted is False
    assert decision.code == "stage_changed_this_turn"


def test_propose_requires_evidence_and_no_existing_partner():
    record = _record("enamored")
    no_evidence = R.validate_action(
        record,
        _propose(evidence_refs=[]),
        actor_id="42",
        allowed_refs=_refs("turn:1:20"),
        stage_before="enamored",
        has_partner=False,
    )
    assert no_evidence.code == "missing_evidence"
    with_partner = R.validate_action(
        record,
        _propose(),
        actor_id="42",
        allowed_refs=_refs("turn:1:20"),
        stage_before="enamored",
        has_partner=True,
        partner_id="9",
    )
    assert with_partner.code == "partner_exists"


def test_valid_proposal_stays_pending_and_does_not_set_the_partner():
    record = _record("enamored")
    decision = R.validate_action(
        record,
        _propose(),
        actor_id="42",
        allowed_refs=_refs("turn:1:20"),
        stage_before="enamored",
        has_partner=False,
    )
    assert decision.accepted is True
    outcome = R.apply_action(record, decision, now=NOW, season=SEASON)
    assert outcome["partner_confirmed"] is False
    assert record["pending_proposal"]["target_user_id"] == "42"


def test_accept_only_for_the_pending_recipient():
    record = _record(
        "enamored",
        pending={
            "target_user_id": "42",
            "reason": "Te quiero.",
            "evidence_refs": ["turn:1:20"],
            "created_at": NOW,
            "season": SEASON,
        },
    )
    wrong = R.validate_action(
        record,
        R.normalize_action({"action": "accept"}),
        actor_id="9",
        allowed_refs=set(),
        stage_before="enamored",
        has_partner=False,
    )
    assert wrong.accepted is False
    assert wrong.code == "wrong_recipient"

    right = R.validate_action(
        record,
        R.normalize_action({"action": "accept"}),
        actor_id="42",
        allowed_refs=set(),
        stage_before="enamored",
        has_partner=False,
    )
    assert right.accepted is True
    outcome = R.apply_action(record, right, now=NOW + 10, season=SEASON)
    assert outcome["partner_confirmed"] is True
    assert record["pending_proposal"] is None


def test_accept_without_pending_proposal_is_ignored():
    decision = R.validate_action(
        _record("enamored"),
        R.normalize_action({"action": "accept"}),
        actor_id="42",
        allowed_refs=set(),
        stage_before="enamored",
        has_partner=False,
    )
    assert decision.accepted is False
    assert decision.code == "no_pending_proposal"


def test_decline_closes_the_proposal_without_partner():
    pending = {
        "target_user_id": "42",
        "reason": "Te quiero.",
        "evidence_refs": [],
        "created_at": NOW,
        "season": SEASON,
    }
    record = _record("enamored", pending=pending)
    decision = R.validate_action(
        record,
        R.normalize_action({"action": "decline", "reason": "prefiero ser amiga"}),
        actor_id="42",
        allowed_refs=set(),
        stage_before="enamored",
        has_partner=False,
    )
    assert decision.accepted is True
    outcome = R.apply_action(record, decision, now=NOW, season=SEASON)
    assert outcome["partner_confirmed"] is False
    assert record["pending_proposal"] is None


def test_unclear_answer_leaves_the_pending_proposal_untouched():
    pending = {
        "target_user_id": "42",
        "reason": "Te quiero.",
        "evidence_refs": [],
        "created_at": NOW,
        "season": SEASON,
    }
    record = _record("enamored", pending=pending)
    decision = R.validate_action(
        record,
        R.normalize_action({"action": "unclear"}),
        actor_id="42",
        allowed_refs=set(),
        stage_before="enamored",
        has_partner=False,
    )
    assert decision.accepted is False
    assert decision.code == "ambiguous"
    assert record["pending_proposal"] == pending


def test_monogamy_caps_other_stages_when_the_partner_is_confirmed():
    world = {
        "winner_id": None,
        "relationships": {
            "9": _record(
                "enamored",
                [_history_entry("r9")],
                pending={"target_user_id": "9"},
            ),
            "42": _record("enamored"),
        },
    }
    R.confirm_partner(world, "42", now=NOW)
    assert world["winner_id"] == "42"
    assert world["relationships"]["9"]["stage"] == "interest"
    assert world["relationships"]["9"]["pending_proposal"] is None


# ---------------------------------------------------------------------------
# Evidencia disponible y temporada
# ---------------------------------------------------------------------------


def test_allowed_refs_include_prior_evidence_and_the_current_turn():
    history = [
        {
            "id": "r1",
            "from": "none",
            "to": "curiosity",
            "evidence_kind": "support",
            "reason": "Me apoyó",
            "evidence_refs": ["turn:1:10"],
            "evidence_summary": "Me apoyó.",
            "season": SEASON,
            "created_at": NOW,
        }
    ]
    record = _record("curiosity", history)
    refs = R.allowed_evidence_refs(record, current_refs=["turn:1:30"])
    assert "turn:1:10" in refs
    assert "ev:r1" in refs
    assert "turn:1:30" in refs
    assert len(refs) == 3


def test_normalize_action_rejects_unknown_actions_and_sanitizes_refs():
    assert R.normalize_action({"action": "casar"}) is None
    action = R.normalize_action(
        {"action": "propose", "reason": "x", "evidence_refs": ["a", 3, ""]}
    )
    assert action.action == "propose"
    assert action.evidence_refs == ("a", "3")


def test_reset_for_season_cancels_proposals_and_clears_the_stage():
    record = _record(
        "enamored",
        history=[_history_entry()],
        pending={"target_user_id": "42"},
    )
    R.reset_for_season(record)
    assert record["stage"] == "none"
    assert record["pending_proposal"] is None
    assert record["history"][0]["id"] == "r1"  # el archivo conserva el pasado


def test_normalize_world_is_idempotent():
    world = {"winner_id": "42", "relationships": {"42": {"stage": "enamored"}}}
    R.normalize_world(world)
    first = copy.deepcopy(world["relationships"])
    R.normalize_world(world)
    assert world["relationships"] == first


def test_current_instruction_alone_is_not_enough_evidence():
    decision = R.validate_stage_update(
        _record("none"),
        _update(),
        allowed_refs=_refs("turn:1:10"),
        current_ref="turn:1:10",
        instruction_only=True,
    )
    assert decision.accepted is False
    assert decision.code == "instruction_only"


def test_an_instruction_turn_cannot_advance_even_with_past_evidence():
    decision = R.validate_stage_update(
        _record("none"),
        _update(evidence_refs=["turn:1:10", "turn:1:30"]),
        allowed_refs=_refs("turn:1:10", "turn:1:30"),
        current_ref="turn:1:30",
        instruction_only=True,
    )
    assert decision.accepted is False
    assert decision.code == "instruction_only"


def test_historical_evidence_alone_cannot_advance_a_stage():
    """Un turno sin señal nueva no cambia la etapa aunque cite el pasado."""
    record = _record("interest", history=[_history_entry()])
    decision = R.validate_stage_update(
        record,
        _update(stage="enamored", evidence_refs=["ev:r1"]),
        allowed_refs=_refs("ev:r1", "turn:1:30"),
        current_ref="turn:1:30",
    )
    assert decision.accepted is False
    assert decision.code == "no_current_evidence"


def test_generic_praise_alone_is_not_enough_evidence():
    decision = R.validate_stage_update(
        _record("none"),
        _update(),
        allowed_refs=_refs("turn:1:10"),
        current_ref="turn:1:10",
        weak_evidence_only=True,
    )
    assert decision.accepted is False
    assert decision.code == "weak_evidence_only"
