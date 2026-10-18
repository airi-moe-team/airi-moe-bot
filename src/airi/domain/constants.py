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


#: Valores aceptados por `env_flag` (case-insensitive).
ENV_TRUE_VALUES = ("1", "true", "yes", "on")
ENV_FALSE_VALUES = ("0", "false", "no", "off")


def env_flag(name, default):
    """Lee un booleano del entorno (`1/0`, `true/false`, `on/off`...).

    Si falta o no es válido (se avisa con `warnings.warn`), devuelve `default`.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    low = raw.strip().lower()
    if low in ENV_TRUE_VALUES:
        return True
    if low in ENV_FALSE_VALUES:
        return False
    warnings.warn(f"{name}={raw!r} no es un booleano válido; se usa {default}.")
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

# Avisos de estado del bot (conectado/desconectado). Antigüedad máxima de ese
# mensaje pendiente que Airi contesta al arranque (ver AIRI_PENDING_MAX_AGE).
PENDING_MAX_AGE_SECONDS = 24 * 3600

# Escena inicial: ya no se proponen planes con botones; el jugador escribe
# libremente a dónde quiere llevar la cita.
DATE_SCENE_TEXT_MAX = env_int("DATE_SCENE_TEXT_MAX", 120)  # Longitud máx. de la escena.
DATE_SCENE_TIMEOUT = env_int("DATE_SCENE_TIMEOUT", 120)  # Segundos para responder.

DATE_CRISIS_MIN_TURNS = env_int("DATE_CRISIS_MIN_TURNS", 3)  # Turnos antes de crisis.
DATE_END_MIN_TURNS = env_int("DATE_END_MIN_TURNS", 4)  # Turnos antes de poder cerrar.
# Turnos mínimos para que la PALABRA de fin ("fin", "adiós"...) cierre la cita.
DATE_END_KEYWORD_MIN_TURNS = env_int("DATE_END_KEYWORD_MIN_TURNS", 2)
DATE_CRISIS_DROP = env_int("DATE_CRISIS_DROP", 4)  # Caída que desata la crisis.
DATE_LAST_CHANCE_MAX_RECOVERY = env_int("DATE_LAST_CHANCE_MAX_RECOVERY", 12)
DATE_HISTORY_MAX = env_int("DATE_HISTORY_MAX", 20)  # Historial aislado por cita.
DATE_MAX_SECONDS = env_int("DATE_MAX_SECONDS", 5 * 60)  # Duración real de una cita.
DATE_STATES = ("active", "last_chance", "final_scene", "closed")
DATE_DECISIONS = ("continue", "crisis", "end", "question")
LAST_CHANCE_RESULTS = ("success", "partial", "fail", "none")

# Pregunta decisiva de la cita (única): la IA decide el momento, con red de
# seguridad. Cada alternativa trae una probabilidad y un premio/castigo grande.
DATE_QUESTION_MIN_TURNS = env_int("DATE_QUESTION_MIN_TURNS", 2)  # Turnos mínimos previos.
DATE_QUESTION_FORCE_TURN = env_int("DATE_QUESTION_FORCE_TURN", 4)  # Turno en que se fuerza.
# Turnos extra sobre DATE_MAX_TURNS para dar tiempo a la pregunta forzada.
DATE_QUESTION_GRACE_TURNS = env_int("DATE_QUESTION_GRACE_TURNS", 2)
DATE_QUESTION_OPTIONS = env_int("DATE_QUESTION_OPTIONS", 3)  # Alternativas máximas.
DATE_QUESTION_DELTA_MAX = env_int("DATE_QUESTION_DELTA_MAX", 25)  # Swing máximo.
DATE_QUESTION_CRISIS_DROP = env_int("DATE_QUESTION_CRISIS_DROP", 20)  # Fallo grave.
# Segundos que la pregunta puede estar sin respuesta antes de caducar (p. ej.
# si el bot se reinicia y se pierde la vista con los botones).
DATE_QUESTION_TIMEOUT = env_int("DATE_QUESTION_TIMEOUT", 180)
# Segundos mínimos que deben quedar en la cita para poder responder la
# pregunta; si no, no se lanza (o se alarga la cita si la pregunta es forzada).
DATE_QUESTION_MIN_SECONDS = env_int("DATE_QUESTION_MIN_SECONDS", 60)
# Margen extra al alargar la cita para que la pregunta forzada sea respondible.
DATE_QUESTION_TIME_MARGIN = env_int("DATE_QUESTION_TIME_MARGIN", 15)

# Diario de Airi.
DIARY_MAX_ENTRIES = env_int("DIARY_MAX_ENTRIES", 300)  # Tope global (FIFO).
DIARY_KINDS = (
    "meet",
    "gift",
    "date",
    "level",
    "confession",
    "reflection",
    "discovery",
)
DIARY_VIEW_LIMIT = env_int("DIARY_VIEW_LIMIT", 10)  # Entradas mostradas en !diario.

# ============================================================
# IDENTIDAD DE AIRI (self model): banda maleable con guardarraíles
# ============================================================
#
# El núcleo (nombre, rol, honestidad, contrato JSON) vive en SYSTEM_PROMPT y NO
# es editable. El "yo" que Airi puede reescribir es la banda de abajo: rasgos,
# valores, manías, gustos y un auto-concepto. Todos los cambios pasan por
# `apply_self_update`, que impone allowlist, topes, motivo y rate-limit.

# Rasgos numéricos con allowlist fija (int 1..5). El valor base es hacia donde
# decae lentamente la identidad si nadie la moldea.
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

# Límites de contenido (topes + longitud por elemento).
SELF_CONCEPT_MAX_CHARS = env_int("SELF_CONCEPT_MAX_CHARS", 400)
SELF_MAX_VALUES = env_int("SELF_MAX_VALUES", 5)
SELF_VALUE_MAX_CHARS = env_int("SELF_VALUE_MAX_CHARS", 40)
SELF_MAX_QUIRKS = env_int("SELF_MAX_QUIRKS", 8)
SELF_QUIRK_MAX_CHARS = env_int("SELF_QUIRK_MAX_CHARS", 80)
SELF_MAX_TASTES = env_int("SELF_MAX_TASTES", 8)
SELF_TASTE_MAX_CHARS = env_int("SELF_TASTE_MAX_CHARS", 40)
SELF_DISCOVERY_MAX_CHARS = env_int("SELF_DISCOVERY_MAX_CHARS", 200)
SELF_DISCOVERIES_MAX = env_int("SELF_DISCOVERIES_MAX", 50)
SELF_HISTORY_MAX = env_int("SELF_HISTORY_MAX", 200)
SELF_HISTORY_VIEW_LIMIT = env_int("SELF_HISTORY_VIEW_LIMIT", 10)

# Guardarraíles temporales: entre dos cambios de identidad debe pasar este
# intervalo; además, cada clave solo puede cambiar una vez al día.
SELF_UPDATE_MIN_INTERVAL = env_int("SELF_UPDATE_MIN_INTERVAL", 3600)
SELF_KEY_DAILY_LIMIT = env_int("SELF_KEY_DAILY_LIMIT", 1)
SELF_KEY_DAILY_SECONDS = env_int("SELF_KEY_DAILY_SECONDS", 86400)

# Deriva lenta: cada `SELF_DECAY_DAYS` completos sin refuerzo, cada rasgo se
# acerca `SELF_DECAY_STEP` hacia su valor base.
SELF_DECAY_DAYS = env_int("SELF_DECAY_DAYS", 7)
SELF_DECAY_STEP = env_int("SELF_DECAY_STEP", 1)

# Reflexión introspectiva: disparador cada N interacciones del usuario.
SELF_REFLECTION_EVERY_N = env_int("SELF_REFLECTION_EVERY_N", 10)
SELF_REFLECTION_MIN_INTERVAL = env_int("SELF_REFLECTION_MIN_INTERVAL", 3600)
SELF_REFLECTION_MAX_TOKENS = env_int("SELF_REFLECTION_MAX_TOKENS", 300)

# Operaciones permitidas sobre la identidad y sus fuentes auditables.
SELF_UPDATE_OPS = ("add", "remove", "inc", "set", "rewrite_concept", "none")
SELF_UPDATE_SOURCES = ("message", "gift", "date", "reflection", "season")

# Resumen de la cita al cerrarla (memoria que Airi guarda en su diario).
DATE_SUMMARY_MAX_TOKENS = env_int("DATE_SUMMARY_MAX_TOKENS", 220)  # Salida LLM.
DATE_SUMMARY_MAX_CHARS = env_int("DATE_SUMMARY_MAX_CHARS", 400)  # Longitud de la entrada.

# Regalos: un regalo al día por usuario.
GIFT_COOLDOWN = env_int("GIFT_COOLDOWN", 24 * 3600)
MAX_RECENT_GIFTS = env_int("MAX_RECENT_GIFTS", 3)

# ============================================================
# LÍMITES DEL PIPELINE DE RESPUESTA (usados por el dominio)
# ============================================================

# Techo total del servidor LLM (`-c` en llama-server): prompt + generación.
# El cliente recorta historial antes de llamar para no superar este techo.
LLM_CONTEXT_TOKENS = env_int("LLM_CONTEXT_TOKENS", 57000)
# Salida máxima que el bot pide por llamada principal (turno y juicio).
LLM_OUTPUT_TOKENS = env_int("LLM_OUTPUT_TOKENS", 1200)

DATE_ACTION_LABEL_MAX = env_int("DATE_ACTION_LABEL_MAX", 80)
SEARCH_QUERY_MAX_TOKENS = env_int("SEARCH_QUERY_MAX_TOKENS", 64)  # Reformulación búsqueda.
REPETITION_THRESHOLD = env_int("REPETITION_THRESHOLD", 4)
MAX_MEMORIES_PER_USER = env_int("MAX_MEMORIES_PER_USER", 15)
MAX_MEMORY_CHARS = env_int("MAX_MEMORY_CHARS", 160)
DIARY_REFLECTION_MIN_INTERVAL = env_int("DIARY_REFLECTION_MIN_INTERVAL", 600)
DIARY_PROMPT_MAX_USER = env_int("DIARY_PROMPT_MAX_USER", 6)
DIARY_PROMPT_MAX_CHARS = env_int("DIARY_PROMPT_MAX_CHARS", 900)
KNOWN_USERS_PROMPT_MAX = env_int("KNOWN_USERS_PROMPT_MAX", 10)
MAX_HISTORY_MESSAGES = env_int("MAX_HISTORY_MESSAGES", 12)
