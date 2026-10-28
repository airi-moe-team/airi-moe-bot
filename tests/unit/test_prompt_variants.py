"""La candidata compacta es independiente del contrato y del default."""

from airi.domain.prompts import (
    COMPACT_OUTPUT_PROMPT,
    FACTUAL_HONESTY_PROMPT,
    GIF_DECISION_PROMPT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_COMPACT_CANDIDATE,
    build_system_prompt,
)


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
        "emojis",
    ):
        assert concept.casefold() in candidate.casefold()


def test_prompt_variant_only_changes_base_personality_text():
    sections = ["\n\n=== DATO DINÁMICO ===\nvalor\n"]
    current = build_system_prompt(None, sections, variant="current")
    candidate = build_system_prompt(None, sections, variant="compact_candidate")

    assert current.startswith(SYSTEM_PROMPT + FACTUAL_HONESTY_PROMPT)
    assert candidate.startswith(SYSTEM_PROMPT_COMPACT_CANDIDATE + FACTUAL_HONESTY_PROMPT)
    assert current.endswith("".join(sections) + GIF_DECISION_PROMPT)
    assert candidate.endswith("".join(sections) + GIF_DECISION_PROMPT)
    assert "=== DATO DINÁMICO ===" in candidate


def test_prompt_variant_keeps_quick_output_contract_unchanged():
    current = build_system_prompt(None, compact=True, variant="current")
    candidate = build_system_prompt(None, compact=True, variant="compact_candidate")

    assert current.endswith(COMPACT_OUTPUT_PROMPT)
    assert candidate.endswith(COMPACT_OUTPUT_PROMPT)


def test_default_variant_is_byte_for_byte_current_prompt():
    assert build_system_prompt(None) == build_system_prompt(None, variant="current")
