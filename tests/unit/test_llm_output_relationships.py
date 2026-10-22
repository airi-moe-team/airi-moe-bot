"""Contrato JSON de los campos relacionales nuevos."""

from __future__ import annotations

import json

from airi.domain.llm_output import (
    RESPONSE_SCHEMA,
    assistant_history_content,
    parse_model_output,
)
from airi.domain.relationships import EVIDENCE_KINDS, ROMANTIC_STAGES


def _raw(**overrides):
    payload = {
        "reply": "Hola~",
        "gif": "none",
        "memory": "none",
        "diary": "none",
        "affinity_delta": 0,
        "affinity_event": "none",
        "date_decision": "continue",
        "date_reason": "none",
        "last_chance_result": "none",
        "date_question": {"text": "", "options": []},
        "self_update": {
            "key": "none",
            "op": "none",
            "value": "",
            "reason": "",
            "evidence": "",
        },
        "disconnect": {"leave": False, "reason": ""},
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_schema_includes_strict_relationship_objects():
    for name in ("romantic_update", "relationship_action"):
        schema = RESPONSE_SCHEMA["properties"][name]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert name in RESPONSE_SCHEMA["required"]


def test_schema_limits_stages_kinds_and_actions():
    update = RESPONSE_SCHEMA["properties"]["romantic_update"]
    assert set(update["properties"]["stage"]["enum"]) == set(ROMANTIC_STAGES)
    assert "none" in update["properties"]["evidence_kind"]["enum"]
    assert set(EVIDENCE_KINDS) <= set(update["properties"]["evidence_kind"]["enum"])
    action = RESPONSE_SCHEMA["properties"]["relationship_action"]
    assert set(action["properties"]["action"]["enum"]) == {
        "none",
        "propose",
        "accept",
        "decline",
        "unclear",
    }


def test_parse_normalizes_relationship_objects():
    output = parse_model_output(_raw(
        romantic_update={
            "stage": "curiosity",
            "evidence_kind": "support",
            "reason": " Me escuchó ",
            "evidence_refs": ["turn:1:5", "", 3],
            "evidence_summary": "Hablamos de su día.",
        },
        relationship_action={
            "action": "none",
            "reason": "",
            "evidence_refs": [],
        },
    ))
    assert output.romantic_update.stage == "curiosity"
    assert output.romantic_update.evidence_kind == "support"
    assert output.romantic_update.reason == "Me escuchó"
    assert output.romantic_update.evidence_refs == ("turn:1:5", "3")
    assert output.relationship_action is None


def test_parse_ignores_invalid_relationship_payloads():
    output = parse_model_output(_raw(
        romantic_update={"stage": "novios", "evidence_kind": "halago"},
        relationship_action={"action": "casarse"},
    ))
    assert output.romantic_update is None
    assert output.relationship_action is None


def test_parse_is_compatible_with_old_responses_without_the_new_fields():
    output = parse_model_output(_raw())
    assert output.reply == "Hola~"
    assert output.romantic_update is None
    assert output.relationship_action is None


def test_assistant_history_uses_neutral_sentinels_for_actions():
    output = parse_model_output(_raw(
        romantic_update={
            "stage": "curiosity",
            "evidence_kind": "support",
            "reason": "Me escuchó",
            "evidence_refs": ["turn:1:5"],
            "evidence_summary": "",
        },
        relationship_action={
            "action": "propose",
            "reason": "Quiero estar contigo",
            "evidence_refs": ["turn:1:5"],
        },
    ))
    content = json.loads(assistant_history_content(output.reply, output))
    assert content["romantic_update"]["stage"] == "none"
    assert content["relationship_action"]["action"] == "none"
