"""Tests del campo `self_update` en la salida del modelo y el historial."""

import json

from airi.domain.llm_output import (
    RESPONSE_SCHEMA,
    assistant_history_content,
    parse_model_output,
    parse_self_update,
)
from airi.domain.self_model import SELF_UPDATE_SCHEMA, self_update_none
from airi.testing import llm_json


def test_parse_extracts_self_update():
    raw = llm_json(
        "hola",
        self_update={
            "key": "traits.juguetona",
            "op": "inc",
            "value": "1",
            "reason": "me ha hecho reír",
            "evidence": "«me encanta tu risa»",
        },
    )
    output = parse_model_output(raw)
    assert output.self_update["key"] == "traits.juguetona"
    assert output.self_update["op"] == "inc"
    assert output.self_update["value"] == "1"


def test_parse_without_self_update_is_none():
    output = parse_model_output(llm_json("hola"))
    assert output.self_update is None


def test_parse_none_sentinel_is_none():
    output = parse_model_output(
        llm_json("hola", self_update=self_update_none())
    )
    assert output.self_update is None


def test_parse_rejects_garbage():
    assert parse_self_update("no soy un dict") is None
    assert parse_self_update(["x"]) is None
    assert parse_self_update({"op": "inc"}) is None  # sin key
    output = parse_model_output(llm_json("x", self_update="basura"))
    assert output.self_update is None


def test_parse_coerces_numeric_value_to_string():
    parsed = parse_self_update(
        {"key": "traits.timida", "op": "inc", "value": 2,
         "reason": "r", "evidence": "e"}
    )
    assert parsed["value"] == "2"


def test_assistant_history_never_echoes_the_self_change():
    """El cambio de identidad es una acción única: no se repite por inercia."""
    raw = llm_json(
        "hola",
        self_update={"key": "traits.juguetona", "op": "inc", "value": "1",
                     "reason": "r", "evidence": "e"},
    )
    output = parse_model_output(raw)
    payload = json.loads(assistant_history_content("hola", output))
    assert payload["self_update"]["op"] == "none"
    assert payload["self_update"]["key"] == "none"


def test_response_schema_includes_strict_self_update():
    assert "self_update" in RESPONSE_SCHEMA["properties"]
    assert "self_update" in RESPONSE_SCHEMA["required"]
    assert RESPONSE_SCHEMA["properties"]["self_update"] == SELF_UPDATE_SCHEMA
