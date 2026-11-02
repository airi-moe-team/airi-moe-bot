"""Motor de afinidad: niveles, deltas, decay, coronación y ranking."""

from __future__ import annotations

from airi.domain.constants import (
    AFFINITY_BAR_WIDTH,
    AFFINITY_DELTA_MAX,
    AFFINITY_DELTA_MIN,
    AFFINITY_FLOOR,
    AFFINITY_LEVELS,
    CONFESS_THRESHOLD,
    DECAY_PER_DAY,
    FRIENDZONE_CAP,
)

# ============================================================
# NIVELES Y RESUMEN
# ============================================================


def clamp_delta(delta, delta_max=AFFINITY_DELTA_MAX, delta_min=AFFINITY_DELTA_MIN):
    """Limita el cambio de afinidad al rango permitido."""
    try:
        value = int(delta)
    except (TypeError, ValueError):
        return 0
    return max(int(delta_min), min(int(delta_max), value))


def affinity_level(points):
    """Devuelve (nivel, mínimo_actual, mínimo_siguiente_o_None)."""
    try:
        points = int(points)
    except (TypeError, ValueError):
        points = 0
    level_name = AFFINITY_LEVELS[0][1]
    current_min = AFFINITY_LEVELS[0][0]
    for threshold, name in AFFINITY_LEVELS:
        if points >= threshold:
            level_name = name
            current_min = threshold
        else:
            return level_name, current_min, threshold
    return level_name, current_min, None


def level_rank(name):
    """Índice del nivel (mayor = más cercano). -1 si no existe."""
    for i, (_, level_name) in enumerate(AFFINITY_LEVELS):
        if level_name == name:
            return i
    return -1


def can_date(points):
    """Las citas requieren al menos el nivel social 'Amiga'."""
    return level_rank(affinity_level(points)[0]) >= 6


def affinity_summary(points):
    """Devuelve (puntos, nombre_del_nivel, texto_de_progreso)."""
    try:
        points = int(points)
    except (TypeError, ValueError):
        points = 0
    level_name, current_min, next_min = affinity_level(points)
    if next_min is None:
        bar = "█" * AFFINITY_BAR_WIDTH
        progress = f"{bar} ¡Nivel máximo!"
    else:
        span = next_min - current_min
        if span <= 0:
            bar = "█" * AFFINITY_BAR_WIDTH
            progress = f"{bar} nivel más bajo"
        else:
            ratio = max(0.0, min(1.0, (points - current_min) / span))
            filled = int(ratio * AFFINITY_BAR_WIDTH)
            bar = "█" * filled + "░" * (AFFINITY_BAR_WIDTH - filled)
            progress = f"{bar} {int(ratio * 100)}% al siguiente"
    return points, level_name, progress


# ============================================================
# ESTADO
# ============================================================


def default_entry():
    return {
        "points": 0,
        "last_gain": 0.0,
        "last_interaction": 0.0,
        "milestones": [],
    }


def default_preferences():
    return {
        "loves": ["romantico", "tierno", "videojuegos", "lol"],
        "comforts": [],
        "curious_about": [],
        "dislikes": [],
        "boundaries": ["grosero"],
        "favorite_flower": "rosas",
        "favorite_food": "postres y dulces",
    }


def default_world():
    return {
        "winner_id": None,
        "relationship_started_at": None,
        "season": 1,
        "preferences": default_preferences(),
        "relationships": {},
        # Ánimo transitorio de Airi (capa separada de la identidad).
        "mood": None,
        "mood_history": [],
    }


def entry_points(entry):
    if not isinstance(entry, dict):
        return 0
    try:
        return int(entry.get("points", 0) or 0)
    except (TypeError, ValueError):
        return 0


# ============================================================
# MOTOR DE AFINIDAD
# ============================================================


def apply_affinity_delta(
    entry,
    delta,
    now,
    delta_max=AFFINITY_DELTA_MAX,
    delta_min=AFFINITY_DELTA_MIN,
):
    """Aplica decay por inactividad y el cambio juzgado por Airi.

    La afinidad solo cambia por decisión de Airi (el bot ya exige un motivo
    para que el delta no sea 0). No hay cupo diario: devuelve el cambio
    realmente aplicado (limitado por el piso).

    `delta_min` permite swings grandes y simétricos (la pregunta decisiva de
    la cita): por defecto el cambio normal va de -5 a +5.
    """
    if not isinstance(entry, dict):
        raise TypeError("entry debe ser un dict")

    delta = clamp_delta(delta, delta_max, delta_min)

    # 1) Decay por inactividad (días completos sin interactuar).
    #    Si nunca hubo interacción (last == 0), no se aplica decay.
    last = float(entry.get("last_interaction", 0.0) or 0.0)
    if last > 0:
        days = int((float(now) - last) // 86400)
        if days > 0:
            entry["points"] = max(
                AFFINITY_FLOOR, entry_points(entry) - days * DECAY_PER_DAY
            )

    # 2) Cambio decidido por Airi, sin cupo diario.
    entry["points"] = max(AFFINITY_FLOOR, entry_points(entry) + delta)
    if delta > 0:
        entry["last_gain"] = float(now)
    entry["last_interaction"] = float(now)
    return delta


# ============================================================
# FINAL ÚNICO: EL GANADOR
# ============================================================


def maybe_crown_winner(world, affinity_data, now):
    """[Obsoleto] Corona al único ganador si alguien cruza el umbral.

    La feature de relación basada en evidencia ya no usa esta función: la
    afinidad no establece pareja. Se conserva solo por compatibilidad con
    código/tests antiguos. Devuelve el user_id coronado o None.
    """
    if not isinstance(world, dict):
        return None
    if world.get("winner_id"):
        return None

    candidates = []
    for uid, entry in (affinity_data or {}).items():
        if str(uid).startswith("_"):
            continue
        if entry_points(entry) >= CONFESS_THRESHOLD:
            candidates.append((str(uid), entry_points(entry)))

    if not candidates:
        return None

    # Determinista: más puntos; empate -> id menor.
    candidates.sort(key=lambda item: (-item[1], item[0]))
    winner_id = candidates[0][0]
    world["winner_id"] = winner_id
    world["relationship_started_at"] = float(now)
    return winner_id


def is_winner(world, user_id):
    if not isinstance(world, dict):
        return False
    winner = world.get("winner_id")
    return bool(winner) and str(winner) == str(user_id)


def apply_winner_lock(world, affinity_data):
    """Una vez hay ganador, el resto no puede pasar de amistad."""
    winner = (world or {}).get("winner_id") if isinstance(world, dict) else None
    if not winner:
        return
    for uid, entry in (affinity_data or {}).items():
        if str(uid).startswith("_") or not isinstance(entry, dict):
            continue
        if str(uid) == str(winner):
            continue
        if entry_points(entry) > FRIENDZONE_CAP:
            entry["points"] = FRIENDZONE_CAP


# ============================================================
# RANKING
# ============================================================


def ranking(affinity_data, users_data, winner_id=None):
    """Devuelve la tabla de pretendientes ordenada por afinidad."""
    rows = []
    for uid, entry in (affinity_data or {}).items():
        if str(uid).startswith("_") or not isinstance(entry, dict):
            continue
        points = entry_points(entry)
        name = ""
        user = (users_data or {}).get(str(uid))
        if isinstance(user, dict):
            name = user.get("name") or ""
        rows.append({
            "user_id": str(uid),
            "name": name or str(uid),
            "points": points,
            "level": affinity_level(points)[0],
            "is_winner": str(uid) == str(winner_id) if winner_id else False,
        })
    rows.sort(key=lambda r: (-r["points"], r["name"].lower(), r["user_id"]))
    return rows
