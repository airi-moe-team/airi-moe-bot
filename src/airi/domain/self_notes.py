"""Notas privadas de Airi por servidor (decisión A5).

La identidad global (`identity.json`) solo admite campos **tipados**:
rasgos, valores, manías, gustos y un auto-concepto. Quedan **bloqueados** los
descubrimientos libres (texto narrativo) porque son los que más filtran datos
de un servidor hacia los demás.

El aprendizaje libre no se tira: vive en el **ámbito privado del servidor**,
en `world["self_notes"]`, que se persiste en el agregado de ese guild y nunca
se comparte con otro.

Reglas:

- Una nota es una entrada estructurada ``{"ts", "text", "source"}``.
- Se deduplica por texto normalizado (mismo descubrimiento, misma nota).
- Se acota el número de notas (`SELF_NOTES_MAX`) y la longitud del texto
  (`SELF_DISCOVERY_MAX_CHARS`).
- Nada de esto llega a la identidad global: `identity_version` no cambia y el
  fichero `identity.json` no se modifica.

Módulo puro: sin I/O ni Discord.
"""

from __future__ import annotations

from typing import Any

from airi.domain.constants import (
    SELF_DISCOVERY_MAX_CHARS,
    SELF_NOTES_MAX,
)

#: Clave del agregado del guild donde viven las notas privadas.
NOTES_KEY = "self_notes"


def _normalize(text: str) -> str:
    """Minúsculas, sin puntuación y con espacios colapsados."""
    cleaned = "".join(
        ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text
    )
    return " ".join(cleaned.split())


def normalize_notes(raw: Any) -> list[dict]:
    """Normaliza una lista de notas a su forma canónica (en el sitio)."""
    if not isinstance(raw, list):
        return []
    notes: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            ts = float(item.get("ts") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        notes.append({
            "ts": ts,
            "text": text[:SELF_DISCOVERY_MAX_CHARS],
            "source": str(item.get("source") or "reflection"),
        })
    return notes[-SELF_NOTES_MAX:]


def add_note(notes: Any, text: Any, *, now: float, source: str = "reflection",
             max_notes: int | None = None) -> dict | None:
    """Añade una nota privada. Devuelve la entrada o ``None`` si no procede.

    No es idempotente por contenido: si el texto ya existe (mismo contenido
    normalizado), no se duplica y se devuelve ``None``.
    """
    cap = int(max_notes if max_notes is not None else SELF_NOTES_MAX)
    if cap <= 0:
        return None
    clean = str(text or "").strip()[:SELF_DISCOVERY_MAX_CHARS]
    if not clean:
        return None
    current = normalize_notes(notes)
    key = _normalize(clean)
    if any(_normalize(str(n.get("text", ""))) == key for n in current):
        return None
    entry = {
        "ts": float(now),
        "text": clean,
        "source": str(source or "reflection"),
    }
    current.append(entry)
    if len(current) > cap:
        del current[: len(current) - cap]
    if isinstance(notes, list):
        notes[:] = current
    return entry


def recent_notes(notes: Any, limit: int = 3) -> list[str]:
    """Últimos textos de las notas (para el prompt y el render)."""
    limit = max(0, int(limit))
    if limit == 0:
        return []
    return [str(n.get("text", "")) for n in normalize_notes(notes)[-limit:]]


def notes_contain(notes: Any, text: Any) -> bool:
    """True si alguna nota reproduce el texto (normalizado)."""
    key = _normalize(str(text or ""))
    if not key:
        return False
    return any(
        _normalize(str(n.get("text", ""))) == key for n in normalize_notes(notes)
    )


__all__ = [
    "NOTES_KEY",
    "add_note",
    "notes_contain",
    "normalize_notes",
    "recent_notes",
]
