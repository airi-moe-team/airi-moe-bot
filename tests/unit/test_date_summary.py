"""Tests del resumen de cita para el diario: limpieza y prompt."""

from airi.domain.prompts import date_summary_prompt
from airi.domain.text_filters import clean_summary

NOW = 1_000_000.0


def test_clean_summary_strips_emojis_quotes_and_newlines():
    raw = '  "Hoy me sentí feliz 😊\ncon Ana."  '

    assert clean_summary(raw) == "Hoy me sentí feliz con Ana."


def test_clean_summary_truncates_to_max_chars():
    assert clean_summary("x" * 500, max_chars=10) == "x" * 10


def test_clean_summary_empty_on_non_string():
    assert clean_summary(None) == ""
    assert clean_summary(123) == ""


def _session(**overrides):
    session = {
        "scene": "un paseo por el parque",
        "question": {"text": "¿Qué es lo que más te gusta de mí?"},
        "question_result": {"index": 0, "win": True, "delta": 20,
                            "label": "Cómo me escuchas"},
    }
    session.update(overrides)
    return session


def test_date_summary_prompt_includes_scene_question_and_transcript():
    history = [
        {"role": "user", "content": "Ana: hola"},
        {"role": "assistant", "content": '{"reply":"*sonríe* Hola~"}'},
    ]

    prompt = date_summary_prompt(_session(), "recovered", history)

    assert "un paseo por el parque" in prompt
    assert "¿Qué es lo que más te gusta de mí?" in prompt
    assert "Cómo me escuchas" in prompt
    assert "Acertó" in prompt
    assert "Ana: hola" in prompt
    assert "Airi: *sonríe* Hola~" in prompt  # se extrae el reply del JSON


def test_date_summary_prompt_handles_missing_question_and_history():
    prompt = date_summary_prompt(
        {"scene": "el cine"}, "ending", []
    )

    assert "el cine" in prompt
    assert "no hubo pregunta decisiva" in prompt
    assert "sin diálogo registrado" in prompt


def test_date_summary_prompt_marks_failed_question():
    session = _session(question_result={"index": 1, "win": False, "delta": -22,
                                        "label": "Eres guapa"})

    prompt = date_summary_prompt(session, "failed_last_chance", [])

    assert "Eres guapa" in prompt
    assert "Falló" in prompt
    assert "-22" in prompt
