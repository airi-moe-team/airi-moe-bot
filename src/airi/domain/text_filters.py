"""Filtros de texto puros sobre las respuestas del modelo."""

from __future__ import annotations

import logging
import re

from airi.domain.constants import REPETITION_THRESHOLD

log = logging.getLogger(__name__)

EMOJI_KEYCAP_RE = re.compile(r"[0-9#*]\uFE0F?\u20E3")
EMOJI_VARIANT_RE = re.compile(r"[\u00A9\u00AE\u2122]\uFE0F")
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
WHITESPACE_BEFORE_PUNCTUATION_RE = re.compile(r"[ \t]+([,.;:!?])")


#: Marcas de plantilla que se escapan del servidor local (ChatML y similares).
MODEL_ARTIFACT_RE = re.compile(
    r"<\|(?:im_end|im_start|endoftext)\|>|</s>",
    re.IGNORECASE,
)
#: Prefijo de rol al inicio de una línea. A mitad de frase no se toca.
ROLE_PREFIX_RE = re.compile(
    r"^[ \t]*(?:###[ \t]*)?(?:User|Assistant|Human)[ \t]*:[ \t]*",
    re.IGNORECASE | re.MULTILINE,
)


def strip_model_artifacts(text):
    """Elimina marcas de plantilla y prefijos de rol del texto del modelo."""
    if not isinstance(text, str):
        return ""
    text = ROLE_PREFIX_RE.sub("", text)
    text = MODEL_ARTIFACT_RE.sub("", text)
    return text.strip()


def clean_reply(text):
    if not isinstance(text, str):
        return ""
    text = strip_model_artifacts(text)
    text = DISCORD_ASSET_LINK_RE.sub("", text)
    text = DISCORD_CUSTOM_EMOJI_RE.sub("", text)
    text = DISCORD_ASSET_URL_RE.sub("", text)
    # Keycap emojis include ASCII characters (e.g. 1️⃣), which the Unicode
    # emoji ranges below do not otherwise recognize.
    text = EMOJI_KEYCAP_RE.sub("", text)
    text = EMOJI_VARIANT_RE.sub("", text)
    text = EMOJI_RE.sub("", text)
    text = EMOJI_MODIFIERS_RE.sub("", text)
    text = WHITESPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", text)
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

def strip_trailing_question(text: str) -> str:
    """Recorta la oración interrogativa final.

    Red de seguridad determinista contra el patrón «preguntón» (charla casual
    que encadena cierres con pregunta): si la respuesta termina en `?`, se
    elimina esa oración final —span desde el último `¿` de apertura— y el resto
    se devuelve limpio. Si la pregunta no lleva `¿` o `¿` está al inicio, cae al
    recorte por delimitadores de oración (., !, ¡, ~, * y salto de línea).
    Nunca devuelve vacío: si no queda texto fuera de la pregunta, se devuelve
    la respuesta tal cual.
    """
    cleaned = (text or "").rstrip()
    if not cleaned or not cleaned.endswith("?"):
        return text

    # 1) Delimitador natural: el último '¿' que abre la oración final.
    open_idx = cleaned.rfind("¿")
    if open_idx > 0:
        remainder = cleaned[:open_idx].rstrip()
        return remainder if remainder.strip() else text

    # 2) Fallback sin '¿': última oración por delimitadores de cierre.
    sentence_start = max(
        cleaned.rfind(ch, 0, -1) for ch in (".", "!", "¡", "\n", "*", "~")
    )
    if sentence_start < 0:
        return text
    remainder = cleaned[:sentence_start + 1].rstrip()
    return remainder if remainder.strip() else text


def strip_trailing_questions(text: str, *, max_rounds: int = 4) -> str:
    """Recorta varias preguntas encadenadas al final de una respuesta."""
    result = text
    for _ in range(max_rounds):
        trimmed = strip_trailing_question(result)
        if trimmed == result:
            break
        result = trimmed
    return result


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
