"""La regla de honestidad factual viaja en todos los contratos."""

from __future__ import annotations

from airi.domain.prompts import FACTUAL_HONESTY_PROMPT, build_system_prompt


def test_prompt_sin_web_incluye_la_regla():
    assert FACTUAL_HONESTY_PROMPT in build_system_prompt(None)


def test_prompt_con_web_incluye_la_regla():
    assert FACTUAL_HONESTY_PROMPT in build_system_prompt("Fuente 1: datos")


def test_prompt_compacto_incluye_la_regla():
    assert FACTUAL_HONESTY_PROMPT in build_system_prompt(None, compact=True)
