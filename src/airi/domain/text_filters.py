"""Filtros de texto puros sobre las respuestas del modelo."""

from __future__ import annotations

import logging
import re

from airi.domain.constants import DATE_SUMMARY_MAX_CHARS, REPETITION_THRESHOLD

log = logging.getLogger(__name__)

EMOJI_RE = re.compile(
    "["
    "\\U0001F1E6-\\U0001F1FF"
    "\\U0001F300-\\U0001FAFF"
    "\\u2600-\\u26FF"
    "\\u2700-\\u27BF"
    "]+"
)
EMOJI_MODIFIERS_RE = re.compile(
    "["
    "\\U0001F3FB-\\U0001F3FF"
    "\\uFE0E-\\uFE0F"
    "\\u200D"
    "\\u20E3"
    "]+"
)
DISCORD_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_]+:\d+>")
DISCORD_ASSET_LINK_RE = re.compile(
    r"\[[^\]]*\]\(https?://(?:www\.)?discord(?:app)?\.com/assets/[^)]*\)",
    re.IGNORECASE,
)
DISCORD_ASSET_URL_RE = re.compile(
    r"https?://(?:www\.)?discord(?:app)?\.com/assets/\S+",
    re.IGNORECASE,
)


def clean_reply(text):
    if not isinstance(text, str):
        return ""
    text = DISCORD_ASSET_LINK_RE.sub("", text)
    text = DISCORD_CUSTOM_EMOJI_RE.sub("", text)
    text = DISCORD_ASSET_URL_RE.sub("", text)
    text = EMOJI_RE.sub("", text)
    text = EMOJI_MODIFIERS_RE.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def clean_summary(text, max_chars=DATE_SUMMARY_MAX_CHARS):
    """Normaliza el resumen libre del LLM (sin emojis/markdown, longitud tope).

    Se usa para la entrada de diario que Airi escribe al cerrar una cita.
    """
    text = clean_reply(text)
    if not text:
        return ""
    # Un resumen es una reflexión breve: una sola línea, sin comillas de fuera.
    text = re.sub(r"\s*\n\s*", " ", text)
    text = text.strip().strip('"').strip("'").strip()
    return text[:max_chars].strip()

def remove_repeated_previous_reply(answer, history):
    if not answer or len(history) < 2:
        return answer
    # El último mensaje del historial es el mensaje actual del usuario.
    previous = next(
        (
            item.get("content", "")
            for item in reversed(history[:-1])
            if item.get("role") == "assistant"
        ),
        "",
    )
    # Desde que el historial guarda JSON, hay que extraer el "reply" interior.
    # (Import local: llm_output importa este módulo, evitamos ciclo.)
    from airi.domain.llm_output import extract_reply_field

    previous = extract_reply_field(previous) or previous
    previous = clean_reply(previous)
    current = clean_reply(answer)
    if previous and current.startswith(previous):
        remainder = current[len(previous):].strip()
        log.warning(
            "Se detectó que el modelo repitió la respuesta anterior; "
            "se elimina el prefijo duplicado."
        )
        return remainder or None
    return answer

def strip_repetition_loop(text):
    """Trunca la respuesta si detecta un bucle de repetición al final."""
    if not text:
        return text
    words = text.split()
    if len(words) < 12:
        return text
    for n in (4, 5, 6, 8, 10):
        if len(words) < n * REPETITION_THRESHOLD:
            continue
        tail = words[-n:]
        count = 0
        idx = len(words)
        while idx - n >= 0 and words[idx - n:idx] == tail:
            count += 1
            idx -= n
        if count >= REPETITION_THRESHOLD:
            truncated = " ".join(words[:idx]).strip()
            log.warning(
                "Bucle de repetición detectado (%d repeticiones de %d palabras); "
                "respuesta truncada.",
                count, n,
            )
            return truncated or None
    return text
