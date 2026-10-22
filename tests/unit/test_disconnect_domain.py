"""Contrato de desconexión voluntaria y coherencia narrativa."""

from __future__ import annotations

from airi.domain.llm_output import parse_disconnect, parse_model_output
from airi.domain.narrative_claims import (
    disconnect_claim_problem,
    mentions_leaving,
)
from airi.testing import llm_json


def test_parse_disconnect_requires_leave_and_reason():
    assert parse_disconnect({"leave": True, "reason": "me voy a dormir"}) == {
        "leave": True,
        "reason": "me voy a dormir",
    }
    assert parse_disconnect({"leave": False, "reason": "me quedo"}) is None
    assert parse_disconnect({"leave": True, "reason": ""}) is None
    assert parse_disconnect(None) is None


def test_parse_model_output_exposes_disconnect():
    raw = llm_json(
        "Buenas noches, me voy a dormir.",
        disconnect={"leave": True, "reason": "me voy a dormir"},
    )
    output = parse_model_output(raw)
    assert output.disconnect == {"leave": True, "reason": "me voy a dormir"}


def test_parse_model_output_ignores_disconnect_without_reason():
    raw = llm_json(
        "Buenas noches.",
        disconnect={"leave": True, "reason": ""},
    )
    output = parse_model_output(raw)
    assert output.disconnect is None


def test_narrative_coherence_detects_false_departure():
    assert mentions_leaving("me voy a dormir") is True
    assert mentions_leaving("no me voy a dormir") is False
    assert disconnect_claim_problem("me voy a dormir", False) is not None
    assert disconnect_claim_problem("buenas noches", True) is None
    assert disconnect_claim_problem("me quedo", True) is not None


def test_parse_model_output_keeps_plain_conversation_without_disconnect():
    output = parse_model_output(llm_json("Hola, ¿qué tal?"))
    assert output.disconnect is None
