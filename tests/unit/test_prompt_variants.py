"""La candidata compacta es independiente del contrato y del default."""

from airi.domain.gifs import ALLOWED_GIF_TYPES
from airi.domain.prompts import (
    COMPACT_OUTPUT_PROMPT,
    CONCISE_DRAFTING_GUIDANCE,
    DECISION_LIGHT_DRAFTING_GUIDANCE,
    DECISION_LIGHT_REPLY_GUIDANCE,
    FACTUAL_HONESTY_PROMPT,
    GIF_REACTION_SECTION,
    ONE_PASS_DRAFTING_GUIDANCE,
    OUTPUT_CONTRACT_PROMPT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_COMPACT_CANDIDATE,
    build_system_prompt,
    self_model_prompt_section,
)
from airi.domain.self_model import default_self


def test_compact_candidate_is_shorter_and_preserves_core_rules():
    candidate = SYSTEM_PROMPT_COMPACT_CANDIDATE

    assert len(candidate) < len(SYSTEM_PROMPT) * 0.75
    for concept in (
        "Airi",
        "intención",
        "opinión",
        "afinidad",
        "sentimientos románticos",
        "memoria",
        "español",
    ):
        assert concept.casefold() in candidate.casefold()
    assert "escala actual de traits (1–5)" in candidate
    assert "nunca una obligación" in candidate


def test_prompt_variant_only_changes_base_personality_text():
    sections = ["\n\n=== DATO DINÁMICO ===\nvalor\n"]
    current = build_system_prompt(None, sections, variant="current")
    candidate = build_system_prompt(None, sections, variant="compact_candidate")

    assert current.startswith(SYSTEM_PROMPT + FACTUAL_HONESTY_PROMPT)
    assert candidate.startswith(SYSTEM_PROMPT_COMPACT_CANDIDATE + FACTUAL_HONESTY_PROMPT)
    assert current.endswith("".join(sections) + GIF_REACTION_SECTION + OUTPUT_CONTRACT_PROMPT)
    assert candidate.endswith("".join(sections) + GIF_REACTION_SECTION + OUTPUT_CONTRACT_PROMPT)
    assert "=== DATO DINÁMICO ===" in candidate


def test_prompt_variant_keeps_quick_output_contract_unchanged():
    current = build_system_prompt(None, compact=True, variant="current")
    candidate = build_system_prompt(None, compact=True, variant="compact_candidate")

    assert current.endswith(COMPACT_OUTPUT_PROMPT)
    assert candidate.endswith(COMPACT_OUTPUT_PROMPT)


def test_default_variant_is_byte_for_byte_current_prompt():
    assert build_system_prompt(None) == build_system_prompt(None, variant="current")


def test_gif_priority_candidate_changes_only_gif_tie_break_guidance():
    current = build_system_prompt(None, variant="previous_current_candidate")
    candidate = build_system_prompt(None, variant="gif_priority_candidate")

    assert "=== REACCIONES VISUALES Y SELECCIÓN DE GIF ===" in candidate
    assert "Ante un saludo, wave suele encajar; shy también puede encajar" not in candidate
    assert candidate == current


def test_one_pass_candidate_adds_direct_response_rule_to_gif_priority():
    candidate = build_system_prompt(None, variant="one_pass_candidate")
    current = build_system_prompt(None, variant="previous_current_candidate")

    assert "=== REACCIONES VISUALES Y SELECCIÓN DE GIF ===" in candidate
    assert "No explores ni compares borradores" in candidate
    assert "Conserva respuestas extensas cuando la petición lo requiera" in candidate
    expected = current.replace(
        CONCISE_DRAFTING_GUIDANCE, ONE_PASS_DRAFTING_GUIDANCE
    )
    assert candidate == expected


def test_decision_light_candidate_changes_only_targeted_prompt_guidance():
    current = build_system_prompt(None, variant="current")
    candidate = build_system_prompt(None, variant="decision_light_candidate")

    assert candidate == current
    assert build_system_prompt(None, variant="current") == current
    assert "El GIF no necesita coincidir con mood.label" in candidate
    gif_instruction = candidate.split('- "gif":', 1)[1].split('- "mood":', 1)[0]
    assert "Valores permitidos:" in gif_instruction
    assert "sigue los significados establecidos en REACCIONES VISUALES Y SELECCIÓN DE GIF" in gif_instruction
    assert "no son obligatorias" in candidate
    assert "sin enumerar alternativas" not in candidate


def test_decision_light_candidate_preserves_compact_contract_schema():
    current = build_system_prompt(None, compact=True, variant="current")
    candidate = build_system_prompt(None, compact=True, variant="decision_light_candidate")

    assert candidate.startswith(current[: current.index(COMPACT_OUTPUT_PROMPT)])
    assert '"gif": Identificador de la reacción visual' in candidate
    assert "Valores permitidos:" in candidate
    assert "acciones narrativas entre asteriscos cuando aporten" in candidate


def test_current_promotes_decision_light_guidance_and_keeps_legacy_rollback():
    current = build_system_prompt(None, variant="current")
    candidate = build_system_prompt(None, variant="decision_light_candidate")
    legacy = build_system_prompt(None, variant="previous_current_candidate")

    assert current == candidate
    assert "valores permitidos:" in current.split(
        '- "gif":', 1
    )[1].split('- "mood":', 1)[0].casefold()
    assert "una formulación sencilla y completa es suficiente" in current
    assert "no son obligatorias" in current
    assert "wave suele encajar; shy también puede encajar" not in legacy
    assert "no enumeres alternativas" in legacy.casefold()
    assert legacy.count(GIF_REACTION_SECTION) == 1


def test_gif_semantics_are_centralized_for_every_prompt_variant():
    reaction_ids = ALLOWED_GIF_TYPES - {"none"}
    expected_meanings = {
        "angry": "Mostrar enfado o irritación",
        "baka": "Reaccionar con indignación juguetona ante una tontería",
        "shy": "Sonrojarse, avergonzarse o mostrar pudor visible",
        "wave": "Saludar o despedirse moviendo la mano",
    }

    for variant in (
        "current",
        "compact_candidate",
        "gif_priority_candidate",
        "one_pass_candidate",
        "decision_light_candidate",
        "previous_current_candidate",
    ):
        for compact in (False, True):
            prompt = build_system_prompt(None, variant=variant, compact=compact)
            assert prompt.count("=== REACCIONES VISUALES Y SELECCIÓN DE GIF ===") == 1
            assert "Guía de GIFs:" not in prompt
            assert "Ante un saludo, wave suele encajar; shy también puede encajar" not in prompt
            section = prompt.split("=== REACCIONES VISUALES Y SELECCIÓN DE GIF ===", 1)[1]
            section = section.split("=== FORMATO DE SALIDA", 1)[0]
            for gif_id in reaction_ids:
                assert f"`{gif_id}`" in section
            for gif_id, meaning in expected_meanings.items():
                assert f"`{gif_id}` — {meaning}" in section
            gif_field = prompt.split('- "gif":', 1)[1].split('- "mood":', 1)[0]
            assert "Valores permitidos:" in gif_field
            assert "sigue los significados establecidos en REACCIONES VISUALES Y SELECCIÓN DE GIF" in gif_field
            assert "mood.label" not in gif_field


def test_both_variants_use_current_dynamic_traits_without_static_overrides():
    self_state = default_self()
    self_state["traits"]["expresiva"] = 1
    self_state["traits"]["timida"] = 5
    dynamic_section = self_model_prompt_section({"self": self_state})

    for variant, base in (
        ("current", SYSTEM_PROMPT),
        ("compact_candidate", SYSTEM_PROMPT_COMPACT_CANDIDATE),
    ):
        prompt = build_system_prompt(None, [dynamic_section], variant=variant)
        assert prompt.startswith(base + FACTUAL_HONESTY_PROMPT)
        assert "Mis rasgos (1-5): expresiva 1, timida 5" in prompt
        assert "Eres dulce, expresiva, cariñosa" not in prompt
        assert "Sé dulce, expresiva, cariñosa" not in prompt


def test_biography_is_injected_once_and_not_repeated_in_dynamic_state():
    dynamic_section = self_model_prompt_section({"self": default_self()})
    for variant in ("current", "compact_candidate"):
        prompt = build_system_prompt(None, [dynamic_section], variant=variant)
        assert prompt.count("=== BIOGRAFÍA CANÓNICA FICTICIA ===") == 1
        assert "Clara" not in dynamic_section
        assert "Nerea" not in dynamic_section
        assert "Gael" not in dynamic_section
