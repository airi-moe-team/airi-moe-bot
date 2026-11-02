"""Contrato puro para la decisión de Airi ante una invitación a cita."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DateInvitationDecision:
    decision: str
    reply: str


def parse_date_invitation_decision(payload):
    """Valida la respuesta del modelo; devuelve None si no es segura de usar."""
    if not isinstance(payload, dict):
        return None
    decision = payload.get("decision")
    reply = payload.get("reply")
    if decision not in ("accept", "reject") or not isinstance(reply, str):
        return None
    reply = " ".join(reply.split())
    if not reply:
        return None
    return DateInvitationDecision(decision=decision, reply=reply[:300])
