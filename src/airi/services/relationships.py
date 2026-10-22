"""Fachada de casos de uso del estado romántico por usuario.

Coordina el dominio puro (`airi.domain.relationships`) con el agregado
persistente (`AppState.world`) dentro de la transacción del turno. No escribe
por su cuenta: usa los callbacks de `AppState` para que el commit siga siendo
atómico.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from airi.domain.affinity import apply_winner_lock, is_winner
from airi.domain.relationship_claims import (
    looks_like_romance_instruction,
    looks_like_weak_romance_evidence,
)
from airi.domain.relationships import (
    Decision,
    RelationshipAction,
    RelationshipFingerprint,
    StageUpdate,
    allowed_evidence_refs,
    apply_action,
    apply_update,
    confirm_partner,
    normalize_relationship,
    normalize_world,
    prompt_evidence,
    turn_ref,
    validate_action,
    validate_stage_update,
)
from airi.services.state import AppState


@dataclass
class RelationshipOutcome:
    """Resultado trazable de aplicar un turno relacional."""

    stage_before: str = "none"
    stage_after: str = "none"
    update_entry: dict | None = None
    update_decision: Decision | None = None
    action_decision: Decision | None = None
    action_applied: str = "none"
    partner_confirmed: bool = False
    pending_proposal: dict | None = None
    errors: list = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.update_entry or self.action_applied != "none" or self.partner_confirmed
        )


class RelationshipService:
    """Lee, valida y aplica el estado relacional de una persona concreta."""

    def __init__(self, state: AppState):
        self.state = state

    # ------------------------------------------------------------------
    # Lectura para el prompt (sin mutar el estado)
    # ------------------------------------------------------------------

    def current_ref(self, turn_key: str | None, *, channel_id=0, user_id=None) -> str:
        key = str(turn_key or "")
        if not key:
            key = f"local:{channel_id}:{user_id or 'anon'}"
        return turn_ref(key)

    def _raw_record(self, user_id) -> dict:
        world = self.state.world if isinstance(self.state.world, dict) else {}
        relationships = world.get("relationships")
        if not isinstance(relationships, dict):
            return normalize_relationship(None)
        return normalize_relationship(relationships.get(str(user_id)))

    def view(self, user_id, *, turn_key=None, channel_id=0, now=None) -> dict:
        """Vista aislada de la relación del interlocutor actual."""
        uid = str(user_id)
        record = self._raw_record(uid)
        refs = allowed_evidence_refs(
            record,
            current_refs=[
                self.current_ref(turn_key, channel_id=channel_id, user_id=uid)
            ],
        )
        return {
            "stage": record["stage"],
            "history": prompt_evidence(record),
            "allowed_refs": sorted(refs),
            "pending": record["pending_proposal"],
            "is_partner": is_winner(self.state.world, uid),
        }

    def fingerprint(self, user_id) -> RelationshipFingerprint:
        """Huella previa al commit para detectar cambios concurrentes."""
        return RelationshipFingerprint.of(self._raw_record(user_id))

    # ------------------------------------------------------------------
    # Aplicación dentro del commit
    # ------------------------------------------------------------------

    def apply(
        self,
        user_id,
        *,
        update: StageUpdate | None,
        action: RelationshipAction | None,
        turn_key=None,
        channel_id=0,
        now: float,
        season: int,
        display_name: str = "alguien",
        current_turn_text: str = "",
    ) -> RelationshipOutcome:
        uid = str(user_id)
        name = display_name or self.state.display_name(uid)
        normalize_world(self.state.world)
        world = self.state.world
        record = self._state_relationship(uid)

        stage_before = record["stage"]
        current_ref = self.current_ref(
            turn_key, channel_id=channel_id, user_id=uid
        )
        refs = allowed_evidence_refs(record, current_refs=[current_ref])
        outcome = RelationshipOutcome(stage_before=stage_before, stage_after=stage_before)

        update_decision = validate_stage_update(
            record,
            update,
            allowed_refs=refs,
            current_ref=current_ref,
            instruction_only=looks_like_romance_instruction(current_turn_text),
            weak_evidence_only=looks_like_weak_romance_evidence(current_turn_text),
        )
        outcome.update_decision = update_decision
        if not update_decision.accepted and update_decision.code != "no_change":
            outcome.errors.append(f"romantic_update:{update_decision.code}")
        if update_decision.accepted:
            outcome.update_entry = apply_update(
                record,
                update_decision,
                now=now,
                season=season,
                actor_id=uid,
            )

        partner = world.get("winner_id")
        action_decision = validate_action(
            record,
            action,
            actor_id=uid,
            allowed_refs=refs,
            stage_before=stage_before,
            has_partner=bool(partner),
            partner_id=str(partner) if partner else None,
        )
        outcome.action_decision = action_decision
        if not action_decision.accepted and action_decision.code not in (
            "no_change",
            "ambiguous",
        ):
            outcome.errors.append(f"relationship_action:{action_decision.code}")
        if action_decision.accepted and action_decision.action is not None:
            act = action_decision.action.action
            act_outcome = apply_action(
                record, action_decision, now=now, season=season
            )
            outcome.action_applied = act
            outcome.pending_proposal = act_outcome["pending_proposal"]
            if act_outcome["partner_confirmed"]:
                confirm_partner(world, uid, now=now)
                apply_winner_lock(world, self.state.affinity)
                outcome.partner_confirmed = True
                outcome.pending_proposal = None
                self.state.log_diary_event(
                    "confession",
                    uid,
                    f"Hoy {name} me ha dicho que sí. Después de todo lo que hemos "
                    "vivido, ahora somos pareja.",
                    now=now,
                )
            elif act == "propose":
                self.state.log_diary_event(
                    "confession",
                    uid,
                    f"Me he armado de valor y le he preguntado a {name} si quiere "
                    "ser mi pareja. Ahora espero su respuesta.",
                    now=now,
                )
            elif act == "decline":
                self.state.log_diary_event(
                    "confession",
                    uid,
                    f"{name} me ha dicho que no quiere estar conmigo. Me ha dolido, "
                    "pero prefiero saberlo.",
                    now=now,
                )

        if outcome.changed:
            current = self._raw_record(uid)
            outcome.stage_after = current["stage"]
            if outcome.pending_proposal is None:
                outcome.pending_proposal = current["pending_proposal"]
            self.state.save_world()
            if outcome.partner_confirmed:
                self.state.save_affinity()
        return outcome

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _state_relationship(self, user_id) -> dict:
        world = self.state.world
        relationships = world.get("relationships")
        if not isinstance(relationships, dict):
            relationships = {}
            world["relationships"] = relationships
        key = str(user_id)
        record = relationships.get(key)
        if not isinstance(record, dict):
            record = normalize_relationship(None)
            relationships[key] = record
        return record
