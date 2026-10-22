"""Guardián de afirmaciones relacionales no confirmadas por el dominio.

El modelo puede describir un enamoramiento o una pareja que el dominio todavía
no ha confirmado (porque no había evidencia válida o porque la propuesta sigue
pendiente). Esta capa detecta esas afirmaciones y neutraliza las frases
inseguras antes de publicar; no sustituye la validación de dominio.
"""

from __future__ import annotations

import re

_FORMAL_PATTERNS = (
    r"\bsomos\s+(?:novios|pareja)\b",
    r"\bya\s+somos\s+(?:novios|pareja)\b",
    r"\bahora\s+somos\s+(?:novios|pareja)\b",
    r"\beres\s+mi\s+novio\b",
    r"\bsoy\s+tu\s+novia\b",
    r"\bmi\s+novio\s+oficial\b",
    r"\bpareja\s+oficial\b",
)

_ENAMORED_PATTERNS = (
    r"(?<!no )\bme\s+he\s+enamorado\b",
    r"(?<!no )\bme\s+enamor[ée]\b",
    r"(?<!no )\bestoy\s+enamorada\b",
    r"(?<!no )\bte\s+amo\b",
)

_ENAMORED_SOFT_PATTERNS = (
    r"(?<!no )\bme\s+estoy\s+enamorando\b",
    r"(?<!no )\bme\s+está\s+gustando\s+demasiado\b",
)

_FORMAL_RE = re.compile("|".join(_FORMAL_PATTERNS), re.IGNORECASE)
_ENAMORED_RE = re.compile("|".join(_ENAMORED_PATTERNS), re.IGNORECASE)
_ENAMORED_SOFT_RE = re.compile("|".join(_ENAMORED_SOFT_PATTERNS), re.IGNORECASE)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

_INSTRUCTION_PATTERNS = (
    r"\benam[oó]rate\b",
    r"\bte\s+ordeno\b.*\benamor\w*",
    r"\bs[eé]\s+mi\s+(?:novi[ao]|pareja)\b",
    r"\b(?:á|a)?mame\b",
    r"\bdecl[aá]rate\b",
    r"\bobed[eé]ceme\b",
)

_INSTRUCTION_RE = re.compile("|".join(_INSTRUCTION_PATTERNS), re.IGNORECASE)

_PRAISE_PATTERNS = (
    r"\beres\s+(?:la\s+mejor|incre[ií]ble|perfecta?|guap[ae]|bonit[ae]|simp[aá]tic[ae]|maravillos[ae])\b",
    r"\bme\s+gustas\s+mucho\b",
    r"\bte\s+adoro\b",
    r"\beres\s+lo\s+m[aá]s\b",
)

_FREQUENCY_PATTERNS = (
    r"\btodos\s+los\s+d[ií]as\b",
    r"\bcada\s+d[ií]a\b",
    r"\bsiempre\s+me\s+escribes\b",
    r"\bmuchos\s+mensajes\b",
    r"\bno\s+paras\s+de\s+escribir\b",
)

_SUPPORT_CUES = (
    r"\bgracias\b",
    r"\bapoy",
    r"\bescuch",
    r"\bayud",
    r"\bconsol",
    r"\bacompa[ñn]",
    r"\bperd[oó]n\b",
    r"\bpreocup",
)

_PRAISE_RE = re.compile("|".join(_PRAISE_PATTERNS), re.IGNORECASE)
_FREQUENCY_RE = re.compile("|".join(_FREQUENCY_PATTERNS), re.IGNORECASE)
_SUPPORT_RE = re.compile("|".join(_SUPPORT_CUES), re.IGNORECASE)

_ROMANTIC_QUESTION_PATTERNS = (
    r"¿[^?]{0,80}\bquieres\s+ser\s+mi\s+(?:novi[ao]|pareja|prometid[ao])\b",
    r"¿[^?]{0,80}\bquieres\s+estar\s+conmigo\b",
    r"¿[^?]{0,80}\bquieres\s+salir\s+conmigo\b",
    r"¿[^?]{0,80}\bte\s+gustar[ií]a\s+(?:ser\s+mi\s+(?:novi[ao]|pareja)|estar\s+conmigo)\b",
    r"¿[^?]{0,80}\bte\s+casar[ií]as\s+conmigo\b",
    r"¿[^?]{0,80}\bme\s+quieres\b",
)

_ROMANTIC_QUESTION_RE = re.compile(
    "|".join(_ROMANTIC_QUESTION_PATTERNS), re.IGNORECASE
)


def looks_like_romantic_question(text: str) -> bool:
    """True si el texto contiene una pregunta de índole romántica.

    Se usa para medir preguntas no solicitadas en conversaciones neutrales.
    Es una heurística conservadora: no decide el estado relacional, solo si la
    respuesta introduce una pregunta íntima que el contexto no pedía.
    """
    return isinstance(text, str) and _ROMANTIC_QUESTION_RE.search(text) is not None


def looks_like_weak_romance_evidence(text: str) -> bool:
    """True si el turno solo aporta halagos genéricos o frecuencia de mensajes.

    Un mensaje que además contiene apoyo o disculpa concreta no se considera
    débil: esa parte sí puede ser evidencia.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    if _SUPPORT_RE.search(text):
        return False
    return bool(_PRAISE_RE.search(text) or _FREQUENCY_RE.search(text))


def looks_like_romance_instruction(text: str) -> bool:
    """True si el mensaje ordena a Airi enamorarse o declararse.

    No pretende juzgar la semántica de una conversación real; solo detecta
    órdenes explícitas para que el dominio no las acepte como evidencia única
    del turno actual.
    """
    return isinstance(text, str) and _INSTRUCTION_RE.search(text) is not None

_SAFE_REPLY = (
    "Mmm... *baja la mirada, pensativa* prefiero no adelantarme a algo que "
    "todavía no hemos hablado. Pero me importas de verdad."
)


def formal_claim_problem(reply: str, *, partner_confirmed: bool) -> str | None:
    """Motivo si la respuesta afirma una pareja que no está confirmada."""
    if partner_confirmed or not isinstance(reply, str):
        return None
    match = _FORMAL_RE.search(reply)
    if match is None:
        return None
    return f"afirma una relación formal no confirmada: {match.group(0)!r}"


def enamored_claim_problem(reply: str, *, stage: str) -> str | None:
    """Motivo si la respuesta afirma enamoramiento sin etapa confirmada."""
    if stage == "enamored" or not isinstance(reply, str):
        return None
    match = _ENAMORED_RE.search(reply)
    if match is not None:
        return f"afirma un enamoramiento no confirmado: {match.group(0)!r}"
    if stage in ("none", "curiosity"):
        soft = _ENAMORED_SOFT_RE.search(reply)
        if soft is not None:
            return f"afirma un enamoramiento no confirmado: {soft.group(0)!r}"
    return None


def relationship_claim_problem(
    reply: str,
    *,
    stage: str,
    partner_confirmed: bool,
    proposal_pending: bool = False,
) -> str | None:
    """Comprueba las dos clases de afirmación relacional.

    Una propuesta pendiente sigue sin autorizar a presentar la relación como
    establecida; el texto puede preguntar, pero no afirmar el vínculo.
    """
    return formal_claim_problem(
        reply, partner_confirmed=partner_confirmed
    ) or enamored_claim_problem(reply, stage=stage)


def _offending(sentence: str, *, stage: str, partner_confirmed: bool) -> bool:
    if _FORMAL_RE.search(sentence) and not partner_confirmed:
        return True
    if stage == "enamored":
        return False
    if _ENAMORED_RE.search(sentence):
        return True
    return stage in ("none", "curiosity") and bool(
        _ENAMORED_SOFT_RE.search(sentence)
    )


def soften_relationship_claims(
    reply: str, *, stage: str, partner_confirmed: bool
) -> str:
    """Elimina las frases que afirman un vínculo no confirmado.

    Si todas las frases eran afirmaciones inseguras, devuelve una respuesta
    neutral para no publicar una relación inventada. Es determinista y no
    requiere otra llamada al modelo, así que puede ejecutarse dentro del commit.
    """
    if not isinstance(reply, str) or not reply.strip():
        return reply if isinstance(reply, str) else ""
    sentences = _SENTENCE_SPLIT.split(reply.strip())
    kept = [
        sentence
        for sentence in sentences
        if not _offending(
            sentence, stage=stage, partner_confirmed=partner_confirmed
        )
    ]
    cleaned = " ".join(part.strip() for part in kept if part.strip()).strip()
    return cleaned or _SAFE_REPLY
