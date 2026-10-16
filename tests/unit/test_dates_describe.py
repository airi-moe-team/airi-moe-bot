"""Tests de `describe_date_session` (volcado de `!debug cita`)."""

from airi.domain.constants import DATE_MAX_SECONDS
from airi.domain.dates import describe_date_session, new_date_session

NOW = 1_000_000.0


def test_describe_without_session():
    assert describe_date_session(None, NOW) == [("Cita", "no hay ninguna activa")]


def test_describe_reports_core_fields():
    session = new_date_session("la playa", 40, now=NOW)
    session["turns"] = 3

    values = dict(describe_date_session(session, NOW))

    assert values["Escena"] == "la playa"
    assert values["Estado"] == "active"
    assert values["Turnos"].startswith("3/")
    assert values["Afinidad inicial"] == "40"
    assert values["Segundos restantes"] == str(DATE_MAX_SECONDS)
    assert values["Pregunta"] == "no usada"


def test_describe_flags_question_state():
    session = new_date_session("paseo", 40, now=NOW)
    session["question_used"] = True
    session["question_forced"] = True
    session["question_invalid"] = True

    values = dict(describe_date_session(session, NOW))

    assert "usada" in values["Pregunta"]
    assert "forzada" in values["Pregunta"]
    assert "inválida" in values["Pregunta"]


def test_describe_shows_crisis_and_last_chance():
    session = new_date_session("paseo", 40, now=NOW)
    session["state"] = "last_chance"
    session["crisis_reason"] = "me gritó"
    session["last_chance_result"] = "none"

    values = dict(describe_date_session(session, NOW))

    assert values["Estado"] == "last_chance"
    assert values["Crisis"] == "me gritó"


def test_describe_keeps_only_last_three_history_entries():
    session = new_date_session("paseo", 40, now=NOW)
    session["history"] = [
        {"role": "user", "content": f"m{i}"} for i in range(5)
    ]

    rows = describe_date_session(session, NOW)
    history = [value for label, value in rows if label == "Historial"]

    assert len(history) == 3
    assert history[-1] == "user: m4"
    assert all("m0" != item.split(": ")[1] for item in history)


def test_describe_reports_end_keyword():
    session = new_date_session("paseo", 40, now=NOW)
    session["end_keyword"] = "adiós"

    values = dict(describe_date_session(session, NOW))

    assert values["Keyword de fin"] == "adiós"
