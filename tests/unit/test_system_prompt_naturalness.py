"""Contrato de naturalidad: respuestas proporcionadas, variadas y sin fórmulas.

Estos tests fijan las reglas del prompt que hacen que Airi suene más natural:
respuestas proporcionadas al mensaje, acciones narrativas que aportan (no una
por oración), aperturas y cierres variados y preguntas solo cuando tiene
sentido preguntarlas.
"""

from airi.domain.dates import new_date_session
from airi.domain.self_model import default_self
from airi.domain.prompts import (
    DATE_DECISION_PROMPT,
    OUTPUT_CONTRACT_PROMPT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_COMPACT_CANDIDATE,
    date_context_section,
    identity_tags_prompt_section,
    memories_prompt_section,
    self_model_prompt_section,
)




def test_intent_priority_comes_before_variety():
    assert "=== PRIORIDAD DE INTENCIÓN ===" in SYSTEM_PROMPT
    assert "responde a la pregunta pendiente" in SYSTEM_PROMPT
    assert SYSTEM_PROMPT.index("=== PRIORIDAD DE INTENCIÓN ===") < SYSTEM_PROMPT.index(
        "=== VARIEDAD Y NATURALIDAD ==="
    )


def test_personality_is_expressed_as_observable_tendencies():
    assert "=== RASGOS COMO TENDENCIAS (NO ACTUACIÓN) ===" in SYSTEM_PROMPT
    assert "según el valor actual de cada rasgo" in SYSTEM_PROMPT
    assert "no impone una intensidad fija" in SYSTEM_PROMPT


def test_static_prompt_does_not_assign_levels_to_mutable_personality_traits():
    for prompt in (SYSTEM_PROMPT, SYSTEM_PROMPT_COMPACT_CANDIDATE):
        assert "Eres dulce, expresiva, cariñosa" not in prompt
        assert "Sé dulce, expresiva, cariñosa" not in prompt
        assert "espontánea, expresiva y coherente" not in prompt
        for trait in ("Expresiva:", "Tímida:", "Juguetona:", "Celosa:", "Sarcástica:", "Curiosa:"):
            assert trait not in prompt


def test_memory_usage_prioritizes_current_and_relevant_data():
    assert "=== USO DE LA MEMORIA ===" in SYSTEM_PROMPT
    assert "la versión más reciente y explícita prevalece" in SYSTEM_PROMPT



def test_memory_section_hides_superseded_preferences():
    section = memories_prompt_section([
        {"text": "Le encanta el flan.", "status": "superseded"},
        {"text": "Su postre favorito es el tiramisú.", "status": "active"},
    ])
    assert "tiramisú" in section
    assert "flan" not in section



def test_questions_are_not_the_default_ending():
    # La regla dura ("no termines todas tus respuestas con una pregunta")
    # fue sustituida por el empujón dinámico de variedad: solo cuando el
    # último turno de Airi cerró con pregunta se inyecta una nota pidiendo
    # variar el cierre (contrato probado en tests/integration/test_question_variety.py).
    assert "termines todas tus respuestas con una pregunta" not in SYSTEM_PROMPT




def test_dates_have_no_per_turn_buttons():
    """Las citas fluyen como conversación: los botones son solo la pregunta."""
    section = date_context_section(new_date_session("un paseo", 40, now=0))
    assert "NO hay botones, solo tu respuesta" in section
    assert '"actions"' not in OUTPUT_CONTRACT_PROMPT
    assert "date_question" in DATE_DECISION_PROMPT


def test_identity_tags_section_is_present():
    section = identity_tags_prompt_section()
    assert "=== ETIQUETAS DE IDENTIDAD Y CONTEXTO ===" in section
    assert "REGLA DE AISLAMIENTO DE PERSONA" in section


def test_prompt_sentences_are_separated_after_sharing_personal_opinions():
    assert "Puedes bromear, discrepar, contar algo tuyo. Sé selectiva" in SYSTEM_PROMPT


def test_compact_candidate_defines_identity_without_turning_fiction_into_memory():
    candidate = SYSTEM_PROMPT_COMPACT_CANDIDATE
    assert "=== IDENTIDAD NARRATIVA ===" in candidate
    assert "chica virtual" in candidate
    assert "personajes imperfectos" in candidate
    assert "identidad estable" in candidate
    assert "experiencias confirmadas" in candidate
    assert "roleplay" in candidate
    assert "tsundere" not in candidate.lower()
    assert "=== IDENTIDAD NARRATIVA ===" not in SYSTEM_PROMPT


def test_both_personalities_share_fictional_canonical_biography():
    for prompt in (SYSTEM_PROMPT, SYSTEM_PROMPT_COMPACT_CANDIDATE):
        lowered = prompt.lower()
        assert "=== BIOGRAFÍA CANÓNICA FICTICIA ===" in prompt
        assert "clara" in lowered and "mateo" in lowered
        assert "nerea" in lowered and "gael" in lowered
        



def test_each_trait_level_has_distinct_current_behavior_guidance():
    prompts = []
    for value in range(1, 6):
        model = default_self()
        model["traits"]["timida"] = value
        prompts.append(self_model_prompt_section({"self": model}))

    assert len(set(prompts)) == 5
    assert "Timidez: muy baja (1/5)" in prompts[0]
    assert "Timidez: baja (2/5)" in prompts[1]
    assert "Timidez: media (3/5)" in prompts[2]
    assert "Timidez: alta (4/5)" in prompts[3]
    assert "Timidez: muy alta (5/5)" in prompts[4]
    assert all("nunca obligaciones" in prompt for prompt in prompts)
