"""Checks puros de calidad del turno y contrato del revisor semántico.

Este módulo no hace I/O ni conoce Discord/HTTP: recibe el borrador y el
historial, y devuelve issues con evidencia. Lo consume `ConversationService`
para decidir si merece una reparación y para fusionar el veredicto del revisor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping, Sequence

from airi.domain.text_filters import strip_trailing_questions

QualityKind = Literal[
    "repeat",
    "repeat_user",
    "ooc",
    "question_close",
    "disconnect",
    "off_topic",
    "wrong_addressee",
    "nonsense",
    "self_reset",
]
Impact = Literal["breaks_thread", "wrong_person", "incoherent", "self_reset"]
Origin = Literal["deterministic", "review"]

VALID_KINDS = frozenset(
    {
        "repeat",
        "repeat_user",
        "ooc",
        "question_close",
        "disconnect",
        "off_topic",
        "wrong_addressee",
        "nonsense",
        "self_reset",
    }
)
VALID_IMPACTS = frozenset(
    {"breaks_thread", "wrong_person", "incoherent", "self_reset"}
)

#: Los parches deterministas resuelven estos tipos sin gastar una llamada.
DETERMINISTIC_KINDS = frozenset({"question_close"})
#: Estos tipos sí requieren una revisión del modelo (o fail-open si no hay).
LLM_REPAIRABLE_KINDS = frozenset(
    {
        "repeat",
        "repeat_user",
        "ooc",
        "off_topic",
        "wrong_addressee",
        "nonsense",
        "self_reset",
        "disconnect",
    }
)

REPEAT_PREFIX_MIN = 40
REPEAT_USER_PREFIX_MIN = 60
MIN_DRAFT_TOKENS_FOR_OVERLAP = 25
OVERLAP_MIN = 0.60

OOC_PHRASES = (
    "como modelo de lenguaje",
    "como una ia",
    "como asistente virtual",
)


@dataclass(frozen=True)
class QualityIssue:
    """Un problema detectado, siempre con evidencia textual."""

    kind: QualityKind
    impact: Impact
    evidence: str
    origin: Origin = "deterministic"


@dataclass(frozen=True)
class ReviewResult:
    """Veredicto del revisor. `valid=False` significa fail-open."""

    on_topic: bool = True
    right_addressee: bool = True
    coherent: bool = True
    issues: tuple[QualityIssue, ...] = ()
    valid: bool = True


def is_out_of_character(text) -> str | None:
    """Devuelve la frase de asistente detectada, o `None`."""
    if not isinstance(text, str):
        return None
    low = text.casefold()
    for phrase in OOC_PHRASES:
        if phrase in low:
            return phrase
    return None


def normalized_reply(text) -> str:
    """Normaliza una respuesta para compararla contra turnos previos."""
    value = (text or "").lower()
    value = re.sub(r"\*[^*]*\*", " ", value)
    value = re.sub(r"[^\w\s¿?¡!~]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _previous_text(msg: Mapping) -> str:
    content = msg.get("content")
    if isinstance(content, str) and content.lstrip().startswith("{"):
        try:
            data = json.loads(content)
        except ValueError:
            data = None
        if isinstance(data, dict):
            content = data.get("reply")
    return content if isinstance(content, str) else ""


def _repeat_source(
    text,
    history,
    *,
    min_prefix: int,
    include_user: bool,
    min_user_prefix: int,
) -> str | None:
    norm = normalized_reply(text)
    for msg in history or []:
        if not isinstance(msg, Mapping):
            continue
        role = msg.get("role")
        if role == "assistant":
            limit = min_prefix
        elif role == "user" and include_user:
            limit = min_user_prefix
        else:
            continue
        if len(norm) < limit:
            continue
        prev_norm = normalized_reply(_previous_text(msg))
        if len(prev_norm) < limit:
            continue
        if (
            norm.startswith(prev_norm[:limit])
            or prev_norm.startswith(norm[:limit])
        ):
            return role
    return None


def reply_repeats_history(
    text,
    history,
    *,
    min_prefix: int = REPEAT_PREFIX_MIN,
    include_user: bool = False,
    min_user_prefix: int = REPEAT_USER_PREFIX_MIN,
) -> bool:
    """True si `text` copia el arranque de una respuesta o mensaje previo."""
    return (
        _repeat_source(
            text,
            history,
            min_prefix=min_prefix,
            include_user=include_user,
            min_user_prefix=min_user_prefix,
        )
        is not None
    )


def quality_issues(
    reply,
    history,
    *,
    previous_closed_with_question: bool = False,
    min_prefix: int = REPEAT_PREFIX_MIN,
    min_user_prefix: int = REPEAT_USER_PREFIX_MIN,
) -> list[QualityIssue]:
    """Issues deterministas: OOC, repetición y cierre interrogativo repetido."""
    issues: list[QualityIssue] = []
    if not isinstance(reply, str) or not reply.strip():
        return issues

    phrase = is_out_of_character(reply)
    if phrase:
        issues.append(QualityIssue("ooc", "incoherent", phrase))

    source = _repeat_source(
        reply,
        history,
        min_prefix=min_prefix,
        include_user=True,
        min_user_prefix=min_user_prefix,
    )
    if source == "assistant":
        issues.append(QualityIssue("repeat", "breaks_thread", reply[:120]))
    elif source == "user":
        issues.append(QualityIssue("repeat_user", "breaks_thread", reply[:120]))

    if previous_closed_with_question and reply.rstrip().endswith("?"):
        trimmed = strip_trailing_questions(reply)
        if trimmed != reply:
            issues.append(
                QualityIssue(
                    "question_close", "breaks_thread", reply[len(trimmed):].strip()
                )
            )
    return issues


def merge_issues(*groups: Iterable[QualityIssue]) -> tuple[QualityIssue, ...]:
    """Une issues de varias fuentes conservando el primero de cada tipo."""
    seen: set[str] = set()
    merged: list[QualityIssue] = []
    for group in groups:
        for issue in group:
            if issue.kind in seen:
                continue
            seen.add(issue.kind)
            merged.append(issue)
    return tuple(merged)


def _tokens(text, ignored: Sequence[str]) -> set[str]:
    value = str(text or "").casefold()
    for span in ignored:
        if isinstance(span, str) and span:
            value = value.replace(span.casefold(), " ")
    value = re.sub(r"[^\w]+", " ", value)
    return set(value.split())


def token_overlap(draft, revised, *, ignored: Sequence[str] = ()) -> float:
    """Proporción de tokens del borrador que sobreviven en la revisión."""
    draft_tokens = _tokens(draft, ignored)
    if not draft_tokens:
        return 1.0
    revised_tokens = _tokens(revised, ignored)
    if not revised_tokens:
        return 0.0
    return len(draft_tokens & revised_tokens) / len(draft_tokens)


def parse_review(raw, *, draft: str | None = None) -> ReviewResult:
    """Parsea el veredicto del revisor. Nunca lanza; inválido ⇒ fail-open."""
    if not isinstance(raw, str) or not raw.strip():
        return ReviewResult(valid=False)
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return ReviewResult(valid=False)
    if not isinstance(data, dict):
        return ReviewResult(valid=False)

    flags: dict[str, bool] = {}
    for key in ("on_topic", "right_addressee", "coherent"):
        value = data.get(key)
        if not isinstance(value, bool):
            return ReviewResult(valid=False)
        flags[key] = value

    raw_issues = data.get("issues", [])
    if not isinstance(raw_issues, list):
        return ReviewResult(valid=False)

    issues: list[QualityIssue] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        impact = item.get("impact")
        evidence = item.get("evidence")
        if not isinstance(kind, str) or kind not in VALID_KINDS:
            continue
        if not isinstance(impact, str) or impact not in VALID_IMPACTS:
            continue
        if not isinstance(evidence, str) or not evidence.strip():
            continue
        evidence = evidence.strip()
        if isinstance(draft, str) and evidence not in draft:
            continue
        issues.append(QualityIssue(kind, impact, evidence, "review"))

    return ReviewResult(issues=tuple(issues), **flags)
