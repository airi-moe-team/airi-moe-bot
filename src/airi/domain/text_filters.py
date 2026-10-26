"""Filtros de texto puros sobre las respuestas del modelo."""

from __future__ import annotations

import logging
import re

from airi.domain.constants import REPETITION_THRESHOLD

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


NARRATIVE_ACTION_RE = re.compile(r"\*[^*\n]+\*")


def limit_narrative_actions(text, max_actions=1):
    """Deja como mucho ``max_actions`` acotaciones entre asteriscos.

    R8 pide que las acciones sean opcionales y que no se acumulen gestos de la
    misma emoción. El modelo tiende a encadenar dos o tres en un turno; este
    filtro conserva la primera y elimina el resto sin tocar el texto hablado.
    """
    if not isinstance(text, str) or max_actions < 0:
        return text
    matches = list(NARRATIVE_ACTION_RE.finditer(text))
    if len(matches) <= max_actions:
        return text
    result = text
    for match in reversed(matches[max_actions:]):
        result = result[: match.start()] + result[match.end() :]
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r" +([,.;!?])", r"\1", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()

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
