"""Contrato de naturalidad: respuestas proporcionadas, variadas y sin fórmulas.

Estos tests fijan las reglas del prompt que hacen que Airi suene más natural:
respuestas proporcionadas al mensaje, acciones narrativas que aportan (no una
por oración), aperturas y cierres variados y preguntas solo cuando tiene
sentido preguntarlas.
"""

from airi.domain.dates import new_date_session
from airi.domain.prompts import (
    GIF_DECISION_PROMPT,
    SYSTEM_PROMPT,
    date_context_section,
    identity_tags_prompt_section,
)


def test_narrative_actions_are_not_one_per_sentence():
    assert "No añadas asteriscos a cada oración" in SYSTEM_PROMPT
    assert "utiliza una acción narrativa solo" in SYSTEM_PROMPT
    assert "cuando aporte algo" in SYSTEM_PROMPT


def test_answers_are_proportionate_to_the_message():
    assert "Responde de forma proporcionada al mensaje" in SYSTEM_PROMPT
    assert "si te saludan, no escribas un monólogo" in SYSTEM_PROMPT
    assert "no lo reduzcas a una broma" in SYSTEM_PROMPT


def test_questions_are_not_the_default_ending():
    assert "No termines todas tus respuestas con una pregunta" in SYSTEM_PROMPT
    assert "pregunta solo cuando de verdad quieras saber algo" in SYSTEM_PROMPT


def test_variety_of_openings_gestures_and_closings():
    assert "Varía las aperturas, los gestos y las despedidas" in SYSTEM_PROMPT
    assert "no repitas la misma" in SYSTEM_PROMPT


def test_output_contract_asks_for_another_ending_when_repeated():
    assert "otra apertura y otro cierre" in GIF_DECISION_PROMPT
    assert "salvo que te pidan expresamente repetirlo o citarlo" in GIF_DECISION_PROMPT


def test_dates_have_no_per_turn_buttons():
    """Las citas fluyen como conversación: los botones son solo la pregunta."""
    section = date_context_section(new_date_session("un paseo", 40, now=0))
    assert "NO hay botones, solo tu respuesta" in section
    assert '"actions"' not in GIF_DECISION_PROMPT
    assert "date_question" in GIF_DECISION_PROMPT


def test_identity_tags_section_is_present():
    section = identity_tags_prompt_section()
    assert "=== ETIQUETAS DE IDENTIDAD Y CONTEXTO ===" in section
    assert "REGLA DE AISLAMIENTO DE PERSONA" in section
