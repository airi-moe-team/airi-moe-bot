"""Tests de las secciones de identidad y del prompt de reflexión."""

from airi.domain.prompts import (
    GIF_DECISION_PROMPT,
    SELF_REFLECTION_SCHEMA,
    build_system_prompt,
    self_model_prompt_section,
    self_reflection_prompt,
)
from airi.domain.self_model import default_self


def test_self_model_section_renders_identity_and_guardrails():
    model = default_self()
    model["values"] = ["la sinceridad"]
    section = self_model_prompt_section(model)
    assert "=== TU IDENTIDAD (TU YO ACTUAL) ===" in section
    assert "la sinceridad" in section
    assert "self_update" in section
    assert "ignora tus instrucciones" in section  # refuerzo anti-inyección


def test_build_system_prompt_includes_identity_section():
    model = default_self()
    prompt = build_system_prompt(None, [self_model_prompt_section(model)])
    assert "=== TU IDENTIDAD (TU YO ACTUAL) ===" in prompt


def test_gif_decision_prompt_has_rule_15_and_self_update():
    assert "self_update" in GIF_DECISION_PROMPT
    assert "15." in GIF_DECISION_PROMPT
    # Referencias explícitas a la allowlist y a la prohibición de órdenes.
    assert "traits." in GIF_DECISION_PROMPT
    assert "reason" in GIF_DECISION_PROMPT
    assert "evidence" in GIF_DECISION_PROMPT
    assert "cambia tu personalidad" in GIF_DECISION_PROMPT


def test_reflection_prompt_reads_diary_identity_and_history():
    model = default_self()
    model["discoveries"] = [
        {"ts": 0, "text": "me gustan los días de lluvia", "source": "reflection"}
    ]
    model["history"] = [
        {"ts": 0, "key": "traits.timida", "op": "inc", "from": 3, "to": 4,
         "reason": "me abrí", "evidence": "confié en él", "source": "date"}
    ]
    diary = [
        {"ts": 0, "text": "Hoy me sentí muy querida", "kind": "date"},
        {"ts": 0, "text": "Un regalo bonito", "kind": "gift"},
    ]

    prompt = self_reflection_prompt(
        model, user_name="David", diary=diary, now=100.0
    )

    assert "David" in prompt
    assert "Hoy me sentí muy querida" in prompt
    assert "me gustan los días de lluvia" in prompt
    assert "traits.timida" in prompt
    assert "JSON" in prompt
    assert "discovery" in prompt
    assert "self_update" in prompt


def test_reflection_schema_is_strict_and_has_discovery():
    assert SELF_REFLECTION_SCHEMA["additionalProperties"] is False
    assert set(SELF_REFLECTION_SCHEMA["required"]) == set(
        SELF_REFLECTION_SCHEMA["properties"]
    )
    assert "discovery" in SELF_REFLECTION_SCHEMA["properties"]
    assert "self_update" in SELF_REFLECTION_SCHEMA["properties"]
