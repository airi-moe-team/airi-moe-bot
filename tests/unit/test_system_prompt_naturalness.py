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
    memories_prompt_section,
)


def test_narrative_actions_are_not_one_per_sentence():
    assert "No añadas asteriscos a cada oración" in SYSTEM_PROMPT
    assert "utiliza una acción narrativa solo" in SYSTEM_PROMPT
    assert "cuando aporte algo" in SYSTEM_PROMPT


def test_answers_are_proportionate_to_the_message():
    assert "Responde de forma proporcionada al mensaje" in SYSTEM_PROMPT
    assert "No impongas un número fijo de frases" in SYSTEM_PROMPT
    assert "ni añadas" in SYSTEM_PROMPT


def test_intent_priority_comes_before_variety():
    assert "=== PRIORIDAD DE INTENCIÓN ===" in SYSTEM_PROMPT
    assert "responde a la pregunta pendiente" in SYSTEM_PROMPT
    assert SYSTEM_PROMPT.index("=== PRIORIDAD DE INTENCIÓN ===") < SYSTEM_PROMPT.index(
        "=== VARIEDAD Y NATURALIDAD ==="
    )


def test_personality_is_expressed_as_observable_tendencies():
    assert "=== RASGOS COMO TENDENCIAS (NO ACTUACIÓN) ===" in SYSTEM_PROMPT
    for trait in ("Expresiva", "Tímida", "Juguetona", "Celosa", "Sarcástica", "Curiosa"):
        assert trait in SYSTEM_PROMPT
    assert "no estés de acuerdo automáticamente para agradar" in SYSTEM_PROMPT
    assert "no inventes haber visto, jugado o vivido algo" in SYSTEM_PROMPT


def test_memory_usage_prioritizes_current_and_relevant_data():
    assert "=== USO DE LA MEMORIA ===" in SYSTEM_PROMPT
    assert "la versión más reciente y explícita prevalece" in SYSTEM_PROMPT
    assert "no recites recuerdos" in SYSTEM_PROMPT


def test_prefab_farewells_are_explicitly_discouraged():
    assert "No uses las frases 'aquí estaré'" in SYSTEM_PROMPT
    assert "sueños dulces" in SYSTEM_PROMPT
    assert "mañana será otro día" in SYSTEM_PROMPT


def test_memory_section_hides_superseded_preferences():
    section = memories_prompt_section([
        {"text": "Le encanta el flan.", "status": "superseded"},
        {"text": "Su postre favorito es el tiramisú.", "status": "active"},
    ])
    assert "tiramisú" in section
    assert "flan" not in section


def test_no_loop_of_recent_narrative_tics():
    assert "PROHIBICIÓN DE BUCLE" in SYSTEM_PROMPT
    assert "Tienes prohibido repetir acciones narrativas" in SYSTEM_PROMPT


def test_questions_are_not_the_default_ending():
    # La regla dura ("no termines todas tus respuestas con una pregunta")
    # fue sustituida por el empujón dinámico de variedad: solo cuando el
    # último turno de Airi cerró con pregunta se inyecta una nota pidiendo
    # variar el cierre (contrato probado en tests/integration/test_question_variety.py).
    assert "termines todas tus respuestas con una pregunta" not in SYSTEM_PROMPT


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
