"""El prompt incluye la decisión contextual de marcharse."""

from __future__ import annotations

from airi.domain.prompts import GIF_DECISION_PROMPT


def test_prompt_declares_disconnect_contract():
    assert '"disconnect"' in GIF_DECISION_PROMPT
    assert "PUEDES MARCHARTE SI TÚ TAMBIÉN QUIERES HACERLO" in GIF_DECISION_PROMPT
    assert "COHERENCIA OBLIGATORIA" in GIF_DECISION_PROMPT


def test_prompt_allows_shared_goodnight_as_a_signal_not_an_order():
    assert "ya vamos a dormir" in GIF_DECISION_PROMPT
    assert "no son una orden" in GIF_DECISION_PROMPT
    assert "Si tú quieres seguir hablando" in GIF_DECISION_PROMPT
