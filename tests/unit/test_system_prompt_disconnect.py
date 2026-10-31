"""El prompt incluye la decisión contextual de marcharse."""

from __future__ import annotations

from airi.domain.prompts import OUTPUT_CONTRACT_PROMPT


def test_prompt_declares_disconnect_contract():
    assert '"disconnect"' in OUTPUT_CONTRACT_PROMPT
    assert "PUEDES MARCHARTE SI TÚ TAMBIÉN QUIERES HACERLO" in OUTPUT_CONTRACT_PROMPT
    assert "COHERENCIA OBLIGATORIA" in OUTPUT_CONTRACT_PROMPT


def test_prompt_allows_shared_goodnight_as_a_signal_not_an_order():
    assert "ya vamos a dormir" in OUTPUT_CONTRACT_PROMPT
    assert "no son una orden" in OUTPUT_CONTRACT_PROMPT
    assert "Si tú quieres seguir hablando" in OUTPUT_CONTRACT_PROMPT
