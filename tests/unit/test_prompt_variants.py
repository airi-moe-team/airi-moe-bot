"""La candidata compacta es independiente del contrato y del default."""

from airi.domain.prompts import (
    COMPACT_OUTPUT_PROMPT,
    FACTUAL_HONESTY_PROMPT,
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
    assert current.endswith("".join(sections) + OUTPUT_CONTRACT_PROMPT)
    assert candidate.endswith("".join(sections) + OUTPUT_CONTRACT_PROMPT)
    assert "=== DATO DINÁMICO ===" in candidate


def test_prompt_variant_keeps_quick_output_contract_unchanged():
    current = build_system_prompt(None, compact=True, variant="current")
    candidate = build_system_prompt(None, compact=True, variant="compact_candidate")

    assert current.endswith(COMPACT_OUTPUT_PROMPT)
    assert candidate.endswith(COMPACT_OUTPUT_PROMPT)


def test_default_variant_is_byte_for_byte_current_prompt():
    assert build_system_prompt(None) == build_system_prompt(None, variant="current")


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
