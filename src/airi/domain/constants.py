"""Constantes y lectores de entorno del dominio.

Equivalente al antiguo `game.py`: se lee del entorno al importar (comportamiento
heredado), pero este módulo no hace I/O de red ni conoce Discord.
"""

from __future__ import annotations

import os
import warnings


def env_int(name, default):
    """Lee un entero del entorno; si falta o no es válido, devuelve `default`."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        warnings.warn(f"{name}={raw!r} no es un entero válido; se usa {default}.")
        return default


def env_float(name, default):
    """Lee un float del entorno; si falta o no es válido, devuelve `default`."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        warnings.warn(f"{name}={raw!r} no es un número válido; se usa {default}.")
        return default


def env_choice(name, default, choices):
    """Lee una opción del entorno; si no es válida, devuelve `default`."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value not in choices:
        warnings.warn(f"{name}={raw!r} no es una opción válida; se usa {default}.")
        return default
    return value


# ============================================================
# CONSTANTES DE JUEGO
# ============================================================

# (puntos_minimos, nombre_del_nivel) — ordenado de menor a mayor.
AFFINITY_LEVELS = (
    (-100, "Bloqueada"),
    (-50, "Enfadada"),
    (-20, "Molesta"),
    (-1, "Distante"),
    (0, "Desconocida"),
    (10, "Conocida"),
    (25, "Amiga"),
    (45, "Interés"),
    (70, "Enamorada"),
    (100, "Novios"),
)

CONFESS_THRESHOLD = env_int("CONFESS_THRESHOLD", 100)  # Afinidad para "Novios".
FRIENDZONE_CAP = env_int("FRIENDZONE_CAP", 44)  # Techo del resto con ganador.
AFFINITY_FLOOR = env_int("AFFINITY_FLOOR", -100)  # Piso mínimo de afinidad.
AFFINITY_DELTA_MIN = env_int("AFFINITY_DELTA_MIN", -5)  # Cambio más duro de Airi.
AFFINITY_DELTA_MAX = env_int("AFFINITY_DELTA_MAX", 5)  # Cambio más dulce de Airi.
DECAY_PER_DAY = env_int("DECAY_PER_DAY", 1)  # Puntos perdidos por día sin hablar.
AFFINITY_BAR_WIDTH = env_int("AFFINITY_BAR_WIDTH", 8)

# Citas: máquina de estados y mecánica de crisis / última oportunidad.
DATE_MAX_TURNS = env_int("DATE_MAX_TURNS", 6)  # Turnos máximos de una cita.
DATE_COOLDOWN = env_int("DATE_COOLDOWN", 6 * 3600)  # Enfriamiento entre citas.
DATE_DELTA_MAX = env_int("DATE_DELTA_MAX", 8)  # Citas: emociones ampliadas.
DATE_BUSY_NOTICE_COOLDOWN = env_int("DATE_BUSY_NOTICE_COOLDOWN", 30)  # Anti-spam.

# Escenas de reserva si el modelo no propone ninguna.
DATE_SCENES = (
    "un paseo por el parque al atardecer",
    "una tarde en una cafetería acogedora",
    "una sesión de cine con palomitas",
    "un día en la playa",
    "una cena a la luz de las velas",
    "una feria con luces de colores",
)
DATE_CRISIS_MIN_TURNS = env_int("DATE_CRISIS_MIN_TURNS", 3)  # Turnos antes de crisis.
DATE_END_MIN_TURNS = env_int("DATE_END_MIN_TURNS", 4)  # Turnos antes de poder cerrar.
DATE_CRISIS_DROP = env_int("DATE_CRISIS_DROP", 4)  # Caída que desata la crisis.
DATE_LAST_CHANCE_MAX_RECOVERY = env_int("DATE_LAST_CHANCE_MAX_RECOVERY", 12)
DATE_HISTORY_MAX = env_int("DATE_HISTORY_MAX", 20)  # Historial aislado por cita.
DATE_MAX_SECONDS = env_int("DATE_MAX_SECONDS", 5 * 60)  # Duración real de una cita.
DATE_STATES = ("active", "last_chance", "final_scene", "closed")
DATE_DECISIONS = ("continue", "crisis", "end", "question")
LAST_CHANCE_RESULTS = ("success", "partial", "fail", "none")

# Pregunta decisiva de la cita: una sola por cita, con botones de respuesta.
# La IA decide el momento (turno 1 = en cuanto el momento lo pida); la red de
# seguridad lanza la pregunta de reserva en `DATE_QUESTION_FORCE_TURN`.
DATE_QUESTION_MIN_TURNS = env_int("DATE_QUESTION_MIN_TURNS", 1)  # Turnos mínimos previos.
DATE_QUESTION_FORCE_TURN = env_int("DATE_QUESTION_FORCE_TURN", 4)  # Turno en que se fuerza.
DATE_QUESTION_OPTIONS = env_int("DATE_QUESTION_OPTIONS", 3)  # Alternativas máximas.
DATE_QUESTION_DELTA_MAX = env_int("DATE_QUESTION_DELTA_MAX", 25)  # Swing máximo.
DATE_QUESTION_CRISIS_DROP = env_int("DATE_QUESTION_CRISIS_DROP", 20)  # Fallo grave.
DATE_QUESTION_TIMEOUT = env_int("DATE_QUESTION_TIMEOUT", 180)  # Segundos del botón.
DATE_QUESTION_MIN_SECONDS = env_int("DATE_QUESTION_MIN_SECONDS", 60)  # Margen mínimo.
DATE_QUESTION_TIME_MARGIN = env_int("DATE_QUESTION_TIME_MARGIN", 15)  # Holgura.

# Diario de Airi.
DIARY_MAX_ENTRIES = env_int("DIARY_MAX_ENTRIES", 300)  # Tope global (FIFO).
DIARY_KINDS = ("meet", "gift", "date", "level", "confession", "reflection")
DIARY_VIEW_LIMIT = env_int("DIARY_VIEW_LIMIT", 10)  # Entradas mostradas en !diario.

# Regalos: un regalo al día por usuario.
GIFT_COOLDOWN = env_int("GIFT_COOLDOWN", 24 * 3600)
MAX_RECENT_GIFTS = env_int("MAX_RECENT_GIFTS", 3)

# ============================================================
# LÍMITES DEL PIPELINE DE RESPUESTA (usados por el dominio)
# ============================================================

DATE_SCENE_MAX_TOKENS = env_int("DATE_SCENE_MAX_TOKENS", 300)  # Citas UI generadas.
SEARCH_QUERY_MAX_TOKENS = env_int("SEARCH_QUERY_MAX_TOKENS", 64)  # Reformulación búsqueda.
DATE_ACTION_LABEL_MAX = env_int("DATE_ACTION_LABEL_MAX", 80)
DATE_SCENE_MAX = env_int("DATE_SCENE_MAX", 4)
REPETITION_THRESHOLD = env_int("REPETITION_THRESHOLD", 4)
# Ámbito de la afinidad que ve el modelo: "recipient" (solo la de quien
# habla) o "all" (la de cada interlocutor, cada uno con la suya).
AFFINITY_VIEW_SCOPE = env_choice(
    "AFFINITY_VIEW_SCOPE", "recipient", ("all", "recipient")
)
MAX_MEMORIES_PER_USER = env_int("MAX_MEMORIES_PER_USER", 15)
MAX_MEMORY_CHARS = env_int("MAX_MEMORY_CHARS", 160)
DIARY_REFLECTION_MIN_INTERVAL = env_int("DIARY_REFLECTION_MIN_INTERVAL", 600)
DIARY_PROMPT_MAX_USER = env_int("DIARY_PROMPT_MAX_USER", 6)
DIARY_PROMPT_MAX_CHARS = env_int("DIARY_PROMPT_MAX_CHARS", 900)
KNOWN_USERS_PROMPT_MAX = env_int("KNOWN_USERS_PROMPT_MAX", 10)
MAX_HISTORY_MESSAGES = env_int("MAX_HISTORY_MESSAGES", 12)

# ============================================================
# IDENTIDAD DE AIRI (self model)
# ============================================================
SELF_TRAIT_MIN = env_int("SELF_TRAIT_MIN", 1)
SELF_TRAIT_MAX = env_int("SELF_TRAIT_MAX", 5)
SELF_TRAITS_ALLOWLIST = (
    "expresiva",
    "timida",
    "juguetona",
    "celosa",
    "sarcastica",
    "curiosa",
)
SELF_BASE_TRAITS = {
    "expresiva": 4,
    "timida": 3,
    "juguetona": 5,
    "celosa": 2,
    "sarcastica": 2,
    "curiosa": 4,
}
SELF_CONCEPT_MAX_CHARS = env_int("SELF_CONCEPT_MAX_CHARS", 400)
SELF_MAX_VALUES = env_int("SELF_MAX_VALUES", 5)
SELF_VALUE_MAX_CHARS = env_int("SELF_VALUE_MAX_CHARS", 40)
SELF_MAX_QUIRKS = env_int("SELF_MAX_QUIRKS", 8)
SELF_QUIRK_MAX_CHARS = env_int("SELF_QUIRK_MAX_CHARS", 80)
SELF_MAX_TASTES = env_int("SELF_MAX_TASTES", 8)
SELF_TASTE_MAX_CHARS = env_int("SELF_TASTE_MAX_CHARS", 40)
SELF_DISCOVERY_MAX_CHARS = env_int("SELF_DISCOVERY_MAX_CHARS", 200)
SELF_DISCOVERIES_MAX = env_int("SELF_DISCOVERIES_MAX", 50)
SELF_NOTES_MAX = env_int("SELF_NOTES_MAX", SELF_DISCOVERIES_MAX)
SELF_HISTORY_MAX = env_int("SELF_HISTORY_MAX", 200)
SELF_HISTORY_VIEW_LIMIT = env_int("SELF_HISTORY_VIEW_LIMIT", 10)
SELF_UPDATE_MIN_INTERVAL = env_int("SELF_UPDATE_MIN_INTERVAL", 3600)
SELF_KEY_DAILY_LIMIT = env_int("SELF_KEY_DAILY_LIMIT", 1)
SELF_KEY_DAILY_SECONDS = env_int("SELF_KEY_DAILY_SECONDS", 86400)
SELF_DECAY_DAYS = env_int("SELF_DECAY_DAYS", 7)
SELF_DECAY_STEP = env_int("SELF_DECAY_STEP", 1)
SELF_REFLECTION_EVERY_N = env_int("SELF_REFLECTION_EVERY_N", 10)
SELF_REFLECTION_MIN_INTERVAL = env_int("SELF_REFLECTION_MIN_INTERVAL", 3600)
SELF_REFLECTION_MAX_TOKENS = env_int("SELF_REFLECTION_MAX_TOKENS", 300)
SELF_UPDATE_OPS = ("add", "remove", "inc", "set", "rewrite_concept", "none")
SELF_UPDATE_SOURCES = ("message", "gift", "date", "reflection", "season")
