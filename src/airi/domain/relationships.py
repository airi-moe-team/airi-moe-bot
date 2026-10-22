"""Dominio relacional: etapas afectivas, evidencia y propuestas de pareja.

La afinidad numérica mide cercanía y elegibilidad; nunca cambia por sí sola la
etapa romántica ni confirma una pareja. Este módulo es puro: no conoce Discord,
HTTP ni filesystem, y no muta el estado global del mundo.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

#: Etapas afectivas ordenadas de menor a mayor compromiso.
ROMANTIC_STAGES = ("none", "curiosity", "interest", "enamored")

#: Catálogo cerrado de evidencias significativas admitidas.
EVIDENCE_KINDS = (
    "support",
    "boundaries",
    "remembered_detail",
    "shared_experience",
    "reconciliation",
)

#: Acciones relacionales estructuradas que puede proponer el modelo.
RELATIONSHIP_ACTIONS = ("none", "propose", "accept", "decline", "unclear")

#: Tope de transiciones conservadas por usuario (las más recientes).
MAX_HISTORY = 50

_STAGE_RANK = {stage: index for index, stage in enumerate(ROMANTIC_STAGES)}


# ============================================================
# Registros y migración
# ============================================================


def default_relationship() -> dict:
    """Registro relacional neutro de un usuario."""
    return {"stage": "none", "history": [], "pending_proposal": None}


def stage_rank(stage: str) -> int:
    return _STAGE_RANK.get(str(stage), 0)


def next_stage(stage: str) -> str | None:
    """Etapa inmediatamente superior, o None si ya es la máxima."""
    index = _STAGE_RANK.get(str(stage), 0)
    if index + 1 >= len(ROMANTIC_STAGES):
        return None
    return ROMANTIC_STAGES[index + 1]


def _safe_str(value: Any, limit: int = 300) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit].strip()


def _clean_refs(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    refs: list[str] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            continue
        ref = str(item).strip()[:200]
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _normalize_history_entry(raw: Any, *, index: int) -> dict | None:
    if not isinstance(raw, dict):
        return None
    from_stage = str(raw.get("from", "none") or "none")
    to_stage = str(raw.get("to", "none") or "none")
    if from_stage not in ROMANTIC_STAGES or to_stage not in ROMANTIC_STAGES:
        return None
    kind = str(raw.get("evidence_kind", "") or "")
    if kind not in EVIDENCE_KINDS and kind != "legacy":
        return None
    reason = _safe_str(raw.get("reason"))
    summary = _safe_str(raw.get("evidence_summary")) or reason
    if not reason:
        return None
    entry_id = _safe_str(raw.get("id"), 80) or f"legacy-{index}"
    try:
        season = int(raw.get("season", 1) or 1)
    except (TypeError, ValueError):
        season = 1
    try:
        created_at = float(raw.get("created_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        created_at = 0.0
    return {
        "id": entry_id,
        "from": from_stage,
        "to": to_stage,
        "evidence_kind": kind,
        "reason": reason,
        "evidence_refs": _clean_refs(raw.get("evidence_refs")),
        "evidence_summary": summary,
        "season": season,
        "created_at": created_at,
    }


def normalize_relationship(record: Any) -> dict:
    """Devuelve un registro relacional válido a partir de datos antiguos."""
    if not isinstance(record, dict):
        return default_relationship()
    stage = str(record.get("stage", "none") or "none")
    if stage not in ROMANTIC_STAGES:
        stage = "none"
    history = []
    raw_history = record.get("history")
    if isinstance(raw_history, list):
        for index, item in enumerate(raw_history[-MAX_HISTORY:]):
            entry = _normalize_history_entry(item, index=index)
            if entry is not None:
                history.append(entry)
    pending = record.get("pending_proposal")
    if not isinstance(pending, dict) or not _safe_str(pending.get("target_user_id"), 80):
        pending = None
    else:
        pending = {
            "target_user_id": _safe_str(pending.get("target_user_id"), 80),
            "reason": _safe_str(pending.get("reason")),
            "evidence_refs": _clean_refs(pending.get("evidence_refs")),
            "created_at": _safe_float(pending.get("created_at")),
            "season": _safe_int(pending.get("season"), 1),
        }
    return {"stage": stage, "history": history, "pending_proposal": pending}


def normalize_world(world: Any) -> dict:
    """Normaliza `world.relationships` y respeta la pareja oficial vigente.

    - No infiere sentimientos desde la afinidad.
    - Si ya hay `winner_id`, lo migra a la etapa `enamored` sin inventar una
      transición ni un motivo histórico.
    - Una etapa sin historial que no sea la pareja oficial se considera un dato
      huérfano y vuelve a `none` (toda transición confirmada tiene evidencia).
    - Con pareja oficial, nadie más puede estar en `enamored`.
    """
    if not isinstance(world, dict):
        return world
    raw = world.get("relationships")
    relationships: dict[str, dict] = {}
    if isinstance(raw, dict):
        for uid, record in raw.items():
            key = str(uid)
            if key.startswith("_"):
                continue
            relationships[key] = normalize_relationship(record)

    winner = world.get("winner_id")
    winner_key = str(winner) if winner not in (None, "", 0) else None
    if winner_key is not None:
        record = relationships.get(winner_key)
        if record is None:
            record = default_relationship()
            relationships[winner_key] = record
        record["stage"] = "enamored"

    for uid, record in relationships.items():
        if uid == winner_key:
            record["pending_proposal"] = None
            continue
        if winner_key is not None:
            record["pending_proposal"] = None
        if record["stage"] != "none" and not record["history"]:
            record["stage"] = "none"
        if winner_key is not None and record["stage"] == "enamored":
            record["stage"] = "interest"

    world["relationships"] = relationships
    return world


# ============================================================
# Contratos normalizados del modelo
# ============================================================


@dataclass(frozen=True)
class StageUpdate:
    stage: str
    evidence_kind: str
    reason: str
    evidence_refs: tuple[str, ...]
    evidence_summary: str


@dataclass(frozen=True)
class RelationshipAction:
    action: str
    reason: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    """Resultado de validar un candidato relacional."""

    accepted: bool
    code: str
    actor_id: str | None = None
    from_stage: str = "none"
    to_stage: str = "none"
    reason: str = ""
    evidence_summary: str = ""
    update: StageUpdate | None = None
    action: RelationshipAction | None = None


def normalize_update(raw: Any) -> StageUpdate | None:
    """Sanea un `romantic_update` propuesto por el modelo."""
    if not isinstance(raw, dict):
        return None
    stage = _safe_str(raw.get("stage"), 40).lower()
    kind = _safe_str(raw.get("evidence_kind"), 40).lower()
    if stage in ("", "none", "null") or kind in ("", "none", "null"):
        return None
    if stage not in ROMANTIC_STAGES or kind not in EVIDENCE_KINDS:
        return None
    return StageUpdate(
        stage=stage,
        evidence_kind=kind,
        reason=_safe_str(raw.get("reason")),
        evidence_refs=tuple(_clean_refs(raw.get("evidence_refs"))),
        evidence_summary=_safe_str(raw.get("evidence_summary")),
    )


def normalize_action(raw: Any) -> RelationshipAction | None:
    """Sanea un `relationship_action` propuesto por el modelo."""
    if not isinstance(raw, dict):
        return None
    action = _safe_str(raw.get("action"), 40).lower()
    if action not in RELATIONSHIP_ACTIONS or action in ("", "none", "null"):
        return None
    return RelationshipAction(
        action=action,
        reason=_safe_str(raw.get("reason")),
        evidence_refs=tuple(_clean_refs(raw.get("evidence_refs"))),
    )


# ============================================================
# Evidencia
# ============================================================


def turn_ref(turn_key: str) -> str:
    """Referencia estable del turno actual."""
    return f"turn:{turn_key}"


def history_ref(entry_id: str) -> str:
    """Referencia estable de una transición ya confirmada."""
    return f"ev:{entry_id}"


def allowed_evidence_refs(record: Any, *, current_refs=()) -> set[str]:
    """Referencias que este usuario y ámbito pueden citar en este turno.

    Las referencias previas provienen del propio historial del usuario, así que
    no pueden filtrar evidencias de otra persona.
    """
    refs = {str(item) for item in current_refs if str(item).strip()}
    normalized = normalize_relationship(record)
    for entry in normalized["history"]:
        refs.add(history_ref(entry["id"]))
        refs.update(entry["evidence_refs"])
    pending = normalized["pending_proposal"]
    if isinstance(pending, dict):
        refs.update(pending["evidence_refs"])
    return refs


def prompt_evidence(record: Any, *, limit: int = 5) -> list[dict]:
    """Evidencias compactas (sin transcripciones) para el prompt."""
    normalized = normalize_relationship(record)
    entries = normalized["history"][-max(1, int(limit)):]
    return [
        {
            "ref": history_ref(entry["id"]),
            "from": entry["from"],
            "to": entry["to"],
            "kind": entry["evidence_kind"],
            "summary": entry["evidence_summary"],
        }
        for entry in entries
    ]


# ============================================================
# Validación y aplicación
# ============================================================


def validate_stage_update(
    record: Any,
    update: StageUpdate | None,
    *,
    allowed_refs: set[str] | None = None,
    current_ref: str | None = None,
    instruction_only: bool = False,
    weak_evidence_only: bool = False,
) -> Decision:
    """Valida una transición afectiva: un paso, con motivo y evidencia."""
    current = normalize_relationship(record)
    stage_before = current["stage"]
    if update is None:
        return Decision(False, "no_change", from_stage=stage_before,
                        to_stage=stage_before)
    target = update.stage
    if target not in ROMANTIC_STAGES or target == "none":
        return Decision(False, "invalid_stage", from_stage=stage_before,
                        to_stage=stage_before)
    if target != next_stage(stage_before):
        return Decision(False, "invalid_transition", from_stage=stage_before,
                        to_stage=stage_before)
    if not update.reason:
        return Decision(False, "missing_reason", from_stage=stage_before,
                        to_stage=target)
    if update.evidence_kind not in EVIDENCE_KINDS:
        return Decision(False, "invalid_evidence_kind", from_stage=stage_before,
                        to_stage=target)
    if not update.evidence_refs:
        return Decision(False, "missing_evidence", from_stage=stage_before,
                        to_stage=target)
    if instruction_only:
        # Una orden de "enamórate" no es evidencia, aunque venga acompañada de
        # referencias antiguas: el turno actual no aporta una señal nueva.
        return Decision(False, "instruction_only", from_stage=stage_before,
                        to_stage=target)
    if weak_evidence_only:
        # Halagos genéricos o frecuencia de mensajes no bastan por sí solos.
        return Decision(False, "weak_evidence_only", from_stage=stage_before,
                        to_stage=target)
    if current_ref is not None and current_ref not in update.evidence_refs:
        # La evidencia histórica da contexto, pero no sustituye a una señal
        # significativa del turno actual (requisito 5.4).
        return Decision(False, "no_current_evidence", from_stage=stage_before,
                        to_stage=target)
    if allowed_refs is not None:
        if any(ref not in allowed_refs for ref in update.evidence_refs):
            return Decision(False, "unknown_evidence", from_stage=stage_before,
                            to_stage=target)
    summary = update.evidence_summary or update.reason
    return Decision(
        True,
        "ok",
        from_stage=stage_before,
        to_stage=target,
        reason=update.reason,
        evidence_summary=summary,
        update=update,
    )


def _history_id(*, actor_id: str, from_stage: str, to_stage: str, now: float,
                season: int, count: int) -> str:
    seed = f"{actor_id}|{season}|{from_stage}|{to_stage}|{float(now):.6f}|{count}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def apply_update(
    record: dict,
    decision: Decision,
    *,
    now: float,
    season: int,
    actor_id: str = "",
) -> dict | None:
    """Aplica una transición aceptada al registro (muta `record`)."""
    if not decision.accepted or decision.update is None:
        return None
    normalized = normalize_relationship(record)
    entry_id = _history_id(
        actor_id=str(actor_id),
        from_stage=decision.from_stage,
        to_stage=decision.to_stage,
        now=now,
        season=season,
        count=len(normalized["history"]),
    )
    entry = {
        "id": entry_id,
        "from": decision.from_stage,
        "to": decision.to_stage,
        "evidence_kind": decision.update.evidence_kind,
        "reason": decision.reason,
        "evidence_refs": list(decision.update.evidence_refs),
        "evidence_summary": decision.evidence_summary,
        "season": int(season),
        "created_at": float(now),
    }
    history = list(normalized["history"])
    history.append(entry)
    record.clear()
    record.update({
        "stage": decision.to_stage,
        "history": history[-MAX_HISTORY:],
        "pending_proposal": normalized["pending_proposal"],
    })
    return entry


def validate_action(
    record: Any,
    action: RelationshipAction | None,
    *,
    actor_id: str,
    allowed_refs: set[str] | None = None,
    stage_before: str | None = None,
    has_partner: bool = False,
    partner_id: str | None = None,
) -> Decision:
    """Valida una propuesta, aceptación o rechazo con el actor actual."""
    current = normalize_relationship(record)
    actor = str(actor_id)
    before = stage_before if stage_before in ROMANTIC_STAGES else current["stage"]
    pending = current["pending_proposal"]

    if action is None or action.action == "none":
        return Decision(False, "no_change", actor_id=actor,
                        from_stage=before, to_stage=current["stage"])

    if action.action not in RELATIONSHIP_ACTIONS:
        return Decision(False, "invalid_action", actor_id=actor,
                        from_stage=before, to_stage=current["stage"])

    if action.action == "propose":
        if current["stage"] == "enamored" and before != "enamored":
            return Decision(False, "stage_changed_this_turn", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        if before != "enamored":
            return Decision(False, "stage_not_confirmed", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        if current["stage"] != "enamored":
            return Decision(False, "stage_changed_this_turn", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        if has_partner:
            return Decision(False, "partner_exists", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        if pending is not None:
            return Decision(False, "proposal_pending", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        if not action.reason:
            return Decision(False, "missing_reason", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        if not action.evidence_refs:
            return Decision(False, "missing_evidence", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        if allowed_refs is not None and any(
            ref not in allowed_refs for ref in action.evidence_refs
        ):
            return Decision(False, "unknown_evidence", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        return Decision(True, "propose", actor_id=actor, from_stage=before,
                        to_stage=current["stage"], reason=action.reason,
                        action=action)

    if action.action == "accept":
        if pending is None:
            return Decision(False, "no_pending_proposal", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        if pending["target_user_id"] != actor:
            return Decision(False, "wrong_recipient", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        if has_partner and partner_id not in (None, actor):
            return Decision(False, "partner_exists", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        return Decision(True, "accept", actor_id=actor, from_stage=before,
                        to_stage=current["stage"], reason=action.reason,
                        action=action)

    if action.action == "decline":
        if pending is None:
            return Decision(False, "no_pending_proposal", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        if pending["target_user_id"] != actor:
            return Decision(False, "wrong_recipient", actor_id=actor,
                            from_stage=before, to_stage=current["stage"])
        return Decision(True, "decline", actor_id=actor, from_stage=before,
                        to_stage=current["stage"], reason=action.reason,
                        action=action)

    # `unclear`: la duda no cambia la pareja ni cierra la propuesta.
    return Decision(False, "ambiguous", actor_id=actor, from_stage=before,
                    to_stage=current["stage"], reason=action.reason,
                    action=action)


def apply_action(
    record: dict, decision: Decision, *, now: float, season: int
) -> dict:
    """Aplica una acción aceptada. Devuelve si confirma la pareja."""
    outcome = {"partner_confirmed": False, "pending_proposal": None}
    if not decision.accepted or decision.action is None:
        return outcome
    normalized = normalize_relationship(record)
    action = decision.action.action
    if action == "propose":
        normalized["pending_proposal"] = {
            "target_user_id": str(decision.actor_id or ""),
            "reason": decision.reason,
            "evidence_refs": list(decision.action.evidence_refs),
            "created_at": float(now),
            "season": int(season),
        }
    elif action == "accept":
        normalized["pending_proposal"] = None
        outcome["partner_confirmed"] = True
    elif action == "decline":
        normalized["pending_proposal"] = None
    record.clear()
    record.update(normalized)
    outcome["pending_proposal"] = normalized["pending_proposal"]
    return outcome


def confirm_partner(world: dict, partner_id: str, *, now: float) -> dict:
    """Confirma la pareja oficial y aplica la monogamia del ámbito."""
    normalize_world(world)
    key = str(partner_id)
    world["winner_id"] = key
    world["relationship_started_at"] = float(now)
    for uid, record in world["relationships"].items():
        if uid == key:
            record["stage"] = "enamored"
            record["pending_proposal"] = None
            continue
        record["pending_proposal"] = None
        if record["stage"] == "enamored":
            record["stage"] = "interest"
    return world


def reset_for_season(record: dict) -> None:
    """Nueva temporada: cancela propuestas y resetea la etapa vigente.

    El historial confirmado se conserva (y además queda archivado por el
    reinicio de temporada); lo que no sobrevive es la propuesta pendiente ni la
    etapa afectiva de la temporada anterior.
    """
    normalized = normalize_relationship(record)
    normalized["stage"] = "none"
    normalized["pending_proposal"] = None
    record.clear()
    record.update(normalized)


def reset_season_world(world: dict) -> dict:
    """Aplica el reinicio de temporada a todos los registros relacionales."""
    normalize_world(world)
    for record in world.get("relationships", {}).values():
        reset_for_season(record)
    return world


# ============================================================
# Huellas para la revalidación previa al commit
# ============================================================


@dataclass(frozen=True)
class RelationshipFingerprint:
    stage: str
    pending_target: str | None
    pending_created_at: float | None

    @classmethod
    def of(cls, record: Any) -> "RelationshipFingerprint":
        normalized = normalize_relationship(record)
        pending = normalized["pending_proposal"]
        return cls(
            stage=normalized["stage"],
            pending_target=(pending or {}).get("target_user_id"),
            pending_created_at=(pending or {}).get("created_at"),
        )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
