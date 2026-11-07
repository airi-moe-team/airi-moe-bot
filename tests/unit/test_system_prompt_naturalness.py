"""Contrato de naturalidad: respuestas proporcionadas, variadas y sin fórmulas.

Estos tests fijan las reglas del prompt que hacen que Airi suene más natural:
respuestas proporcionadas al mensaje, acciones narrativas que aportan (no una
por oración), aperturas y cierres variados y preguntas solo cuando tiene
sentido preguntarlas.
"""

from airi.domain.dates import new_date_session
from airi.domain.prompts import (
    COMPACT_OUTPUT_PROMPT,
    DATE_DECISION_PROMPT,
    OUTPUT_CONTRACT_PROMPT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_COMPACT_CANDIDATE,
    build_system_prompt,
    date_context_section,
    date_contract_section,
    identity_tags_prompt_section,
    memories_prompt_section,
    self_model_prompt_section,
)
from airi.domain.self_model import default_self


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
    assert SYSTEM_PROMPT.count("PROHIBIDO cerrar con pregunta") == 0


def test_unknown_affinity_is_cordial_without_demanding_proof_of_affection():
    from airi.domain.prompts import AFFINITY_TONE_HINTS

    tone = AFFINITY_TONE_HINTS["Desconocida"].lower()
    assert "a la defensiva" not in tone
    assert "barreras altas" not in tone
    assert "demostrar" not in tone


def test_mood_is_transient_and_does_not_override_stable_traits():
    prompt = SYSTEM_PROMPT.lower()
    assert "la timidez indicada por tus rasgos es una tendencia estable" in prompt
    assert "el ánimo del turno es transitorio y no es un rasgo" in prompt


def test_mood_label_and_categories_are_distinct_and_preserve_current_state():
    for prompt in (OUTPUT_CONTRACT_PROMPT,):
        lowered = prompt.lower()
        assert '"label" nombra el estado emocional específico' in lowered
        assert '"categories" son dimensiones emocionales complementarias' in lowered
        assert "no tienen que coincidir" in lowered
        assert 'label="timida"' in lowered
        assert "no cambies la etiqueta" in lowered
        assert "conserva el ánimo actual" in lowered


def test_mood_label_must_use_enum_and_not_describe_social_tone():
    for prompt in (OUTPUT_CONTRACT_PROMPT, COMPACT_OUTPUT_PROMPT):
        lowered = prompt.lower()
        assert "exactamente uno de los valores permitidos" in lowered
        assert '"cordial"' in lowered
        assert "describe" in lowered and "tono social, no una emoción" in lowered
        assert "no inventes etiquetas" in lowered


def test_gif_selection_uses_canonical_values_and_observable_reaction():
    prompt = build_system_prompt()
    lowered = prompt.lower()
    gif_instruction = lowered.split('- "gif":', 1)[1].split('- "mood":', 1)[0]
    assert "valores permitidos:" in gif_instruction
    assert "sigue los significados establecidos en reacciones visuales y selección de gif" in gif_instruction
    assert prompt.count("=== REACCIONES VISUALES Y SELECCIÓN DE GIF ===") == 1
    assert "shy representa vergüenza o pudor visibles" in lowered
    assert "wave` — saludar o despedirse moviendo la mano" in lowered


def test_current_prompts_direct_everyday_replies_and_optional_gestures():
    for prompt in (OUTPUT_CONTRACT_PROMPT, COMPACT_OUTPUT_PROMPT):
        lowered = prompt.lower()
        assert "genera directamente una respuesta natural y proporcionada" in lowered
        assert "una formulación sencilla y completa es suficiente" in lowered
        assert "no son obligatorias" in lowered


def test_date_contract_is_only_injected_for_active_date():
    inactive_prompt = build_system_prompt(sections=[date_contract_section(False)])
    assert '"date_decision"' not in inactive_prompt
    assert '"date_question"' not in inactive_prompt
    active = build_system_prompt(sections=[date_contract_section(True)])
    assert '"date_decision"' in active
    assert '"date_question"' in active


def test_closed_date_session_does_not_render_date_context_or_contract():
    assert date_context_section({"state": "closed", "scene": "cena"}) == ""
    assert date_contract_section(False) == ""


def test_memories_prompt_deduplicates_repeated_events():
    section = memories_prompt_section([
        {"text": "Airi y Alex compartieron una charla sobre sus videojuegos favoritos.", "status": "active"},
        {"text": "Airi y Alex compartieron una charla sobre sus videojuegos favoritos.", "status": "active"},
    ])
    assert section.count("compartieron una charla") == 1




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
