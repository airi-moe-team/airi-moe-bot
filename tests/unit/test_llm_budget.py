"""Tests del presupuesto de contexto del LLM (dominio puro).

Cubren la estimación de tokens y el recorte del historial por los mensajes
más viejos primero, sin tocar nunca el system prompt.
"""

from airi.domain.budget import CHARS_PER_TOKEN, estimate_tokens, fit_history


def test_estimate_tokens_uses_four_chars_per_token():
    assert estimate_tokens("x" * (CHARS_PER_TOKEN * 10)) == 10
    assert estimate_tokens("") == 1
    assert estimate_tokens(None) == 1


def test_fit_history_keeps_everything_when_it_fits():
    history = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "ey"},
    ]

    kept, trimmed = fit_history(
        "system", history, output_tokens=100, context_tokens=1000
    )

    assert kept == history
    assert trimmed is False


def test_fit_history_trims_oldest_first():
    old = {"role": "user", "content": "v" + "iejo" * 200}  # ~200 tokens
    new = {"role": "user", "content": "nuevo"}
    history = [old, new]

    kept, trimmed = fit_history(
        "system", history, output_tokens=100, context_tokens=300
    )

    assert kept == [new]
    assert trimmed is True


def test_fit_history_never_touches_system_prompt():
    # Ni siquiera con un techo imposible se devuelve historial inventado:
    # como mucho queda vacío, el system siempre lo pone el llamador.
    history = [{"role": "user", "content": "hola"}]

    kept, trimmed = fit_history(
        "system", history, output_tokens=999_999, context_tokens=10
    )

    assert kept == []
    assert trimmed is True


def test_fit_history_handles_non_dict_messages():
    kept, trimmed = fit_history(
        "system", ["texto plano"], output_tokens=1, context_tokens=10_000
    )

    assert kept == ["texto plano"]
    assert trimmed is False


def test_fit_history_empty_history():
    kept, trimmed = fit_history(
        "system", [], output_tokens=100, context_tokens=1000
    )

    assert kept == []
    assert trimmed is False
