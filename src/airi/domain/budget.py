"""Presupuesto de contexto del LLM (lógica pura, sin red ni I/O).

El servidor tiene un techo total (`LLM_CONTEXT_TOKENS`: prompt + generación).
Antes de llamar, el cliente estima el prompt (~4 chars/token) y recorta el
historial por los mensajes más viejos primero —nunca el system prompt— para
que el servidor no trunque a ciegas y el modelo no pierda el formato JSON.
"""

from __future__ import annotations

CHARS_PER_TOKEN = 4


def estimate_tokens(text):
    """Estimación barata de tokens (~4 chars/token). Nunca devuelve 0."""
    if not isinstance(text, str):
        text = str(text or "")
    return max(1, len(text) // CHARS_PER_TOKEN)


def _message_tokens(message):
    if isinstance(message, dict):
        return estimate_tokens(message.get("content", ""))
    return estimate_tokens(message)


def fit_history(system_prompt, history, *, output_tokens, context_tokens):
    """Recorta `history` para que `prompt + salida` quepa en el techo.

    Devuelve `(history_ajustado, recorto_bool)`. El system prompt es
    intocable: solo se descartan mensajes del historial, de más viejo a
    más nuevo, hasta que la estimación cuadre o no quede nada que quitar.
    """
    history = list(history or [])
    budget = int(context_tokens) - int(output_tokens)
    system_cost = estimate_tokens(system_prompt)
    total = system_cost + sum(_message_tokens(m) for m in history)
    if total <= budget:
        return history, False
    trimmed = list(history)
    while trimmed and total > budget:
        total -= _message_tokens(trimmed.pop(0))
    return trimmed, len(trimmed) != len(history)
