"""Diario de Airi: entradas, consultas y formato relativo."""

from __future__ import annotations

from airi.domain.constants import DIARY_MAX_ENTRIES

DIARY_KIND_LABELS = {
    "reflection": "Reflexión de Airi",
    "meet": "Encuentro",
    "level": "Relación",
    "date": "Cita",
    "gift": "Regalo",
    "confession": "Confesión",
}


def diary_kind_label(kind):
    """Etiqueta visible que distingue eventos de reflexiones personales."""
    key = str(kind or "").strip().lower()
    return DIARY_KIND_LABELS.get(key, "Evento")


def default_diary():
    return []


def new_diary_entry(kind, user_id, user_name, text, now, season=1):
    return {
        "ts": float(now),
        "kind": str(kind),
        "user_id": str(user_id),
        "user_name": str(user_name or ""),
        "text": str(text or ""),
        "season": int(season or 1),
    }


def add_diary_entry(diary, entry):
    """Añade una entrada al diario respetando el tope FIFO."""
    if not isinstance(diary, list):
        return False
    if not isinstance(entry, dict) or not entry.get("text"):
        return False
    diary.append(entry)
    while len(diary) > DIARY_MAX_ENTRIES:
        diary.pop(0)
    return True


def diary_for_user(diary, user_id, limit=None):
    """Entradas sobre un usuario (orden cronológico), últimas `limit`."""
    if not isinstance(diary, list):
        return []
    key = str(user_id)
    rows = [
        e for e in diary
        if isinstance(e, dict) and str(e.get("user_id")) == key
    ]
    if limit is not None and limit >= 0:
        rows = rows[-limit:]
    return rows


def recent_diary(diary, limit=None):
    """Entradas más recientes del diario (orden cronológico)."""
    if not isinstance(diary, list):
        return []
    rows = [e for e in diary if isinstance(e, dict)]
    if limit is not None and limit >= 0:
        rows = rows[-limit:]
    return rows


def purge_user_diary(diary, user_id):
    """Borra las entradas sobre un usuario. Devuelve cuántas eliminó."""
    if not isinstance(diary, list):
        return 0
    key = str(user_id)
    kept = [
        e for e in diary
        if not (isinstance(e, dict) and str(e.get("user_id")) == key)
    ]
    removed = len(diary) - len(kept)
    diary[:] = kept
    return removed


def format_relative_time(ts, now):
    """Texto humano del tipo 'hace 2 días'."""
    try:
        delta = float(now) - float(ts)
    except (TypeError, ValueError):
        return ""
    if delta < 60:
        return "ahora mismo"
    if delta < 3600:
        return f"hace {int(delta // 60)} min"
    if delta < 86400:
        return f"hace {int(delta // 3600)} h"
    days = int(delta // 86400)
    if days == 1:
        return "ayer"
    return f"hace {days} días"
