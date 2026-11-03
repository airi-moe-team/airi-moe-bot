"""Registro de usuarios conocidos del canal (lógica pura)."""

from __future__ import annotations

import math

#: Ventana para considerar que dos mensajes son la misma sesión de actividad.
ACTIVITY_SESSION_GAP_SECONDS = 30 * 60
#: Muestras de actividad conservadas por usuario (una por sesión).
ACTIVITY_SAMPLES_MAX = 60


def _valid_stamps(raw) -> list[float]:
    """Normaliza el historial de actividad persistido, descartando basura."""
    if not isinstance(raw, list):
        return []
    stamps: list[float] = []
    for value in raw:
        try:
            stamp = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(stamp) and stamp >= 0:
            stamps.append(stamp)
    stamps.sort()
    return stamps


def register_activity(
    users,
    *,
    user_id,
    display_name,
    now,
    session_gap=ACTIVITY_SESSION_GAP_SECONDS,
    max_samples=ACTIVITY_SAMPLES_MAX,
):
    """Actualiza nombre/visitas del usuario. Devuelve True si es nuevo.

    Además de ``last_seen`` (último mensaje) guarda ``activity_ts``: el inicio
    de cada sesión de actividad, es decir, un mensaje separado del anterior por
    al menos ``session_gap``. Esa serie acotada permite inferir el horario
    habitual sin inflar el estado con cada mensaje.
    """
    key = str(user_id)
    entry = users.get(key)
    is_new = not isinstance(entry, dict)
    stamp = float(now)
    if is_new:
        entry = {
            "name": display_name,
            "first_seen": stamp,
            "last_seen": stamp,
            "interactions": 0,
            "activity_ts": [],
        }
        users[key] = entry
    entry["name"] = display_name
    entry["last_seen"] = stamp
    entry["interactions"] = int(entry.get("interactions", 0) or 0) + 1

    history = _valid_stamps(entry.get("activity_ts"))
    if not history or (
        stamp >= history[-1] and stamp - history[-1] >= session_gap
    ):
        history.append(stamp)
    entry["activity_ts"] = history[-max_samples:]
    return is_new
