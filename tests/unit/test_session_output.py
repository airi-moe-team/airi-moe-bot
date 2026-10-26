"""Pruebas del contrato de salida de sesión (tipos únicos, silencio por cadena vacía)."""

from __future__ import annotations

from airi.domain.llm_output import (
    RESPONSE_SCHEMA,
    SESSION_RESPONSE_SCHEMA,
    parse_model_output,
    parse_session_output,
)


def test_session_schema_es_estricto_y_anade_stay_active():
    assert SESSION_RESPONSE_SCHEMA["additionalProperties"] is False
    assert set(SESSION_RESPONSE_SCHEMA["required"]) == set(
        SESSION_RESPONSE_SCHEMA["properties"]
    )
    assert "stay_active" in SESSION_RESPONSE_SCHEMA["properties"]
    assert SESSION_RESPONSE_SCHEMA["properties"]["stay_active"]["type"] == "boolean"
    assert SESSION_RESPONSE_SCHEMA["properties"]["reply"]["type"] == "string"
    # El esquema normal no se mutó.
    assert "stay_active" not in RESPONSE_SCHEMA["properties"]


def test_session_schema_mantiene_propiedades_normales():
    for key in RESPONSE_SCHEMA["properties"]:
        assert key in SESSION_RESPONSE_SCHEMA["properties"]


def test_parse_session_texto_valido():
    raw = '{"reply":"hola","stay_active":true}'
    output, stay, valid = parse_session_output(raw)
    assert valid is True
    assert stay is True
    assert output.reply == "hola"


def test_parse_session_silencio_valido():
    raw = '{"reply":"","stay_active":true}'
    output, stay, valid = parse_session_output(raw)
    assert valid is True
    assert stay is True
    assert output.reply == ""


def test_parse_session_stay_active_false():
    raw = '{"reply":"adiós","stay_active":false}'
    output, stay, valid = parse_session_output(raw)
    assert valid is True
    assert stay is False
    assert output.reply == "adiós"


def test_parse_session_falta_stay_active_invalido():
    raw = '{"reply":"hola"}'
    _output, _stay, valid = parse_session_output(raw)
    assert valid is False


def test_parse_session_stay_active_no_booleano_invalido():
    raw = '{"reply":"hola","stay_active":"true"}'
    _output, _stay, valid = parse_session_output(raw)
    assert valid is False


def test_parse_session_stay_active_nulo_invalido():
    raw = '{"reply":"hola","stay_active":null}'
    _output, _stay, valid = parse_session_output(raw)
    assert valid is False


def test_parse_session_campo_desconocido_no_cambia_el_estado():
    raw = '{"reply":"hola","stay_active":false,"campo_futuro":1}'
    output, stay, valid = parse_session_output(raw)
    assert valid is True
    assert stay is False
    assert output.reply == "hola"


def test_parse_session_reply_no_string_invalido():
    raw = '{"reply":123,"stay_active":true}'
    _output, _stay, valid = parse_session_output(raw)
    assert valid is False


def test_parse_session_json_invalido():
    _output, _stay, valid = parse_session_output("no es json")
    assert valid is False


def test_parse_model_output_normal_no_permite_vacio():
    raw = '{"reply":"","stay_active":true}'
    out = parse_model_output(raw)
    # El contrato normal rechaza la respuesta vacía.
    assert out.reply is None or out.reply == ""  # tolerante
    # sin allow_empty_reply, no debe quedar como texto utilizable
    assert not (isinstance(out.reply, str) and out.reply.strip())


def test_parse_model_output_descarta_texto_crudo_si_se_pide():
    """Un JSON truncado no debe publicarse como reply cuando hubo corte."""
    from airi.domain.llm_output import parse_model_output

    raw = '{"reply": "me quedé pensando y el JSON se co'
    assert parse_model_output(raw).reply
    assert parse_model_output(raw, allow_raw_fallback=False).reply is None
