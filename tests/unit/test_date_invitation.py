"""Validación de la decisión estructurada de una invitación a cita."""

from airi.domain.date_invitation import parse_date_invitation_decision


def test_parse_date_invitation_accepts_accept_and_reject():
    accepted = parse_date_invitation_decision(
        {"decision": "accept", "reply": "¡Sí, me apetece!"}
    )
    rejected = parse_date_invitation_decision(
        {"decision": "reject", "reply": "Hoy prefiero que no."}
    )

    assert accepted.decision == "accept"
    assert accepted.reply == "¡Sí, me apetece!"
    assert rejected.decision == "reject"
    assert rejected.reply == "Hoy prefiero que no."


def test_parse_date_invitation_rejects_invalid_or_missing_fields():
    assert parse_date_invitation_decision({"decision": "maybe", "reply": "x"}) is None
    assert parse_date_invitation_decision({"decision": "accept"}) is None
    assert parse_date_invitation_decision(None) is None


def test_parse_date_invitation_normalizes_reply_and_rejects_empty_reply():
    result = parse_date_invitation_decision(
        {"decision": "accept", "reply": "  Sí,  vamos.  "}
    )

    assert result.reply == "Sí, vamos."
    assert parse_date_invitation_decision(
        {"decision": "accept", "reply": "   "}
    ) is None


def test_parse_date_invitation_limits_reply_length():
    result = parse_date_invitation_decision(
        {"decision": "reject", "reply": "a" * 1000}
    )

    assert len(result.reply) <= 300
