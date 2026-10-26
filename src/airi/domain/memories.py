"""Memorias duraderas de Airi: alta, consolidación, olvido y correcciones.

Las memorias son registros aditivos. Los datos antiguos (solo ``text`` y
``created_at``) se normalizan al leerse. Una corrección explícita no borra el
historial: marca la versión anterior como ``superseded`` y deja la vigente
como ``active`` para que el prompt no mezcle preferencias contradictorias.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from airi.domain.constants import MAX_MEMORIES_PER_USER, MAX_MEMORY_CHARS
from airi.domain.text_filters import clean_reply

ACTIVE = "active"
SUPERSEDED = "superseded"

#: «Mi postre favorito es el tiramisú» / «mis juegos favoritos son...».
_PREFERENCE_RE = re.compile(
    r"\b(?:mi|el|la|mis|los|las)\s+"
    r"(?P<topic>[a-záéíóúüñ][a-záéíóúüñ\s]{1,30}?)\s+"
    r"favorit[oa]s?\s+(?:es|son)\s+"
    r"(?P<value>[^.!?;\n]+)",
    re.IGNORECASE,
)

#: «Mi postre favorito no es el flan, es el tiramisú».
_NO_ES_PREFERENCE_RE = re.compile(
    r"\b(?:mi|el|la|mis|los|las)\s+"
    r"(?P<topic>[a-záéíóúüñ][a-záéíóúüñ\s]{1,30}?)\s+"
    r"favorit[oa]s?\s+no\s+(?:es|son)\s+[^,.;\n]+"
    r",?\s*(?:sino|es|son)\s+"
    r"(?P<value>[^.!?;\n]+)",
    re.IGNORECASE,
)

_CORRECTION_MARKER_RE = re.compile(
    r"\b(?:me\s+equivo\w*|me\s+confund\w*|en\s+realidad|mas\s+bien|"
    r"corrijo|olvida\s+lo\s+que\s+dije|lo\s+que\s+dije\s+antes|"
    r"no\s+es\s+asi|no\s+era\s+asi)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PreferenceCorrection:
    """Preferencia explícita que reemplaza una versión anterior."""

    topic: str
    topic_key: str
    value: str

    @property
    def memory_text(self) -> str:
        plural = self.topic.rstrip().endswith("s")
        if plural:
            return f"Sus {self.topic} favoritos son {self.value}."
        return f"Su {self.topic} favorito es {self.value}."


def _normalize_text(text) -> str:
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    plain = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return " ".join(plain.casefold().split())


def _clean_value(value) -> str:
    return " ".join(str(value or "").strip().split()).strip(
        " .,;:!?¡¿\"'"
    )[:120]


def _extract_preference(text):
    if not isinstance(text, str):
        return None
    match = _NO_ES_PREFERENCE_RE.search(text) or _PREFERENCE_RE.search(text)
    if not match:
        return None
    topic = " ".join(match.group("topic").split()).strip()
    value = _clean_value(match.group("value"))
    if not topic or not value:
        return None
    return topic, _normalize_text(topic), value


def infer_memory_topic(source_text) -> str | None:
    """Deduce el tema de una memoria a partir del mensaje que la originó."""
    extracted = _extract_preference(source_text)
    return extracted[1] if extracted else None


def extract_preference_correction(text) -> PreferenceCorrection | None:
    """Detecta una corrección explícita de preferencia y extrae la vigente."""
    if not isinstance(text, str) or not _CORRECTION_MARKER_RE.search(text):
        return None
    extracted = _extract_preference(text)
    if not extracted:
        return None
    topic, topic_key, value = extracted
    return PreferenceCorrection(topic=topic, topic_key=topic_key, value=value)


def _normalize_entry(entry) -> dict:
    if not isinstance(entry, dict):
        entry = {"text": str(entry)}
    entry.setdefault("created_at", 0.0)
    entry.setdefault("updated_at", entry.get("created_at", 0.0))
    entry.setdefault("source", "legacy")
    entry.setdefault("status", ACTIVE)
    entry.setdefault("confidence", 1.0)
    entry.setdefault("scope", "user")
    entry.setdefault("topic", None)
    return entry


def user_memories(memories, user_id):
    """Lista (siempre existente) de memorias de un usuario, normalizada."""
    key = str(user_id)
    entries = memories.get(key)
    if not isinstance(entries, list):
        entries = []
        memories[key] = entries
    entries[:] = [_normalize_entry(entry) for entry in entries]
    return entries


def active_memories(entries) -> list[dict]:
    """Memorias vigentes, en orden de antigüedad."""
    return [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("status", ACTIVE) != SUPERSEDED
    ]


def relevant_memories(entries, text) -> list[dict]:
    """Memorias vigentes cuyo tema aparece en el mensaje actual."""
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return []
    matches = []
    for entry in active_memories(entries):
        topic = _normalize_text(entry.get("topic"))
        if topic and topic in normalized_text:
            matches.append(entry)
    return matches


def _touch_duplicate(entry, now) -> None:
    entry["updated_at"] = float(now)


def add_memory(
    memories,
    user_id,
    text,
    *,
    now,
    max_items=MAX_MEMORIES_PER_USER,
    max_chars=MAX_MEMORY_CHARS,
    topic=None,
    source="message",
    confidence=1.0,
    scope="user",
    source_text=None,
    turn_key=None,
):
    """Guarda una memoria. Devuelve False si está vacía o es duplicada.

    Si llega un ``topic`` (o se deduce de ``source_text``) y ya existe una
    memoria vigente del mismo tema con otro texto, la anterior pasa a
    ``superseded``. Así una corrección reemplaza sin acumular versiones.
    """
    text = clean_reply(text).strip()[:max_chars].strip()
    if not text:
        return False
    topic = topic or infer_memory_topic(source_text)
    entries = user_memories(memories, user_id)
    active = active_memories(entries)
    lower = _normalize_text(text)
    existing = [_normalize_text(e.get("text", "")) for e in active]

    # Duplicado exacto o casi exacto (solo frases suficientemente largas).
    for old_entry, old in zip(active, existing):
        if lower == old or (
            min(len(lower), len(old)) >= 12 and (lower in old or old in lower)
        ):
            _touch_duplicate(old_entry, now)
            return False

    if topic:
        topic_key = _normalize_text(topic)
        for old_entry in active:
            if _normalize_text(old_entry.get("topic")) == topic_key:
                old_entry["status"] = SUPERSEDED
                old_entry["updated_at"] = float(now)

    entries.append(
        {
            "text": text,
            "created_at": float(now),
            "updated_at": float(now),
            "source": source,
            "status": ACTIVE,
            "confidence": float(confidence),
            "scope": scope,
            "topic": _normalize_text(topic) if topic else None,
            "turn_key": turn_key,
        }
    )
    while len(entries) > max_items:
        superseded_index = next(
            (
                index
                for index, entry in enumerate(entries)
                if entry.get("status") == SUPERSEDED
            ),
            0,
        )
        entries.pop(superseded_index)
    return True


def apply_preference_correction(
    memories,
    user_id,
    correction: PreferenceCorrection,
    *,
    now,
    source="correction",
    source_text=None,
    previous_text=None,
    turn_key=None,
) -> bool:
    """Consolida una corrección explícita como preferencia vigente.

    ``previous_text`` permite enlazar memorias antiguas sin ``topic`` (por
    ejemplo, «Le encanta el flan.» guardada antes de esta versión) con el valor
    que el usuario acaba de corregir.
    """
    entries = user_memories(memories, user_id)
    if previous_text:
        previous = _extract_preference(previous_text)
        if previous and previous[1] == correction.topic_key:
            old_value = _normalize_text(previous[2])
            for entry in active_memories(entries):
                entry_text = _normalize_text(entry.get("text"))
                if old_value and (
                    old_value in entry_text or entry_text in old_value
                ):
                    entry["status"] = SUPERSEDED
                    entry["updated_at"] = float(now)
    return add_memory(
        memories,
        user_id,
        correction.memory_text,
        now=now,
        topic=correction.topic_key,
        source=source,
        confidence=1.0,
        source_text=source_text,
        turn_key=turn_key,
    )


def forget_memory(memories, user_id, index=None):
    """Borra la memoria vigente ``index`` (1-based) o todas si es None."""
    entries = user_memories(memories, user_id)
    if index is None:
        if not entries:
            return False
        memories[str(user_id)] = []
        return True
    active = active_memories(entries)
    if 1 <= index <= len(active):
        entries.remove(active[index - 1])
        return True
    return False


def process_memory_action(
    memories,
    user_id,
    action,
    *,
    now,
    source="message",
    source_text=None,
    turn_key=None,
):
    """Aplica la acción de memoria del modelo (guardar u olvidar).

    Devuelve True solo si se guardó una memoria nueva. ``source_text`` permite
    deducir el tema (p. ej. «postre») sin hardcodear valores concretos.
    """
    if not isinstance(action, str):
        return False
    action = action.strip()
    if not action or action.lower() == "none":
        return False
    forget_match = re.match(r"(?i)^olvidar:\s*(\d+)$", action)
    if forget_match:
        forget_memory(memories, user_id, int(forget_match.group(1)))
        return False
    return add_memory(
        memories,
        user_id,
        action,
        now=now,
        source=source,
        source_text=source_text,
        turn_key=turn_key,
    )
