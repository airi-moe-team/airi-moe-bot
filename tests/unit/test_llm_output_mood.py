"""Contrato de salida del ánimo transitorio."""

from __future__ import annotations

import json

from airi.domain.llm_output import parse_model_output


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


def test_parse_model_output_reads_mood():
    output = parse_model_output(
        _raw(
            mood={
                "label": "juguetona",
                "valence": 2,
                "energy": 4,
                "warmth": 3,
                "cause": "broma compartida",
            }
        )
    )
    assert output.mood["label"] == "juguetona"
    assert output.mood["cause"] == "broma compartida"


def test_parse_model_output_reads_categories():
    output = parse_model_output(
        _raw(
            mood={
                "label": "juguetona",
                "valence": 2,
                "energy": 4,
                "warmth": 3,
                "categories": {
                    "entusiasmo": 4,
                    "tension": 2,
                    "calma": 0,
                    "bajon": 0,
                    "neutral": 0,
                },
                "cause": "none",
            }
        )
    )
    assert output.mood["categories"]["entusiasmo"] == 4
    assert output.mood["categories"]["tension"] == 2


def test_parse_model_output_derives_categories_when_missing():
    output = parse_model_output(
        _raw(
            mood={
                "label": "molesta",
                "valence": -2,
                "energy": 4,
                "warmth": 1,
                "cause": "none",
            }
        )
    )
    assert output.mood["categories"]["tension"] == 4


def test_parse_model_output_tolerates_missing_or_broken_mood():
    assert parse_model_output(_raw()).mood is None
    assert parse_model_output(_raw(mood="none")).mood is None
    assert parse_model_output(_raw(mood={"label": "inexistente"})).mood is None


def test_parse_model_output_cleans_mood_axes():
    output = parse_model_output(
        _raw(
            mood={
                "label": "molesta",
                "valence": -99,
                "energy": 99,
                "warmth": 0,
                "cause": "  me   ignoró  ",
            }
        )
    )
    assert output.mood["valence"] == -2
    assert output.mood["energy"] == 5
    assert output.mood["warmth"] == 1
    assert output.mood["cause"] == "me ignoró"
