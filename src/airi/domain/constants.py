"""Constantes y lectores de entorno del dominio.

Equivalente al antiguo `game.py`: se lee del entorno al importar (comportamiento
heredado), pero este módulo no hace I/O de red ni conoce Discord.
"""

from __future__ import annotations

import json
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


ENV_TRUE_VALUES = ("1", "true", "yes", "on")
ENV_FALSE_VALUES = ("0", "false", "no", "off")


def env_flag(name, default):
    """Lee un booleano del entorno; un valor ausente o inválido usa default."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ENV_TRUE_VALUES:
        return True
    if value in ENV_FALSE_VALUES:
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


def _json_env(name, default, validate):
    """Lee JSON de entorno, lo valida y conserva `default` si no es válido."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return validate(json.loads(raw))
    except (TypeError, ValueError) as exc:
        warnings.warn(
            f"{name} no es válido ({exc}); se usa el valor por defecto.",
            stacklevel=2,
        )
        return default


def _validate_affinity_levels(value):
    if not isinstance(value, list) or len(value) < 7:
        raise ValueError("se requieren al menos siete niveles")
    levels = []
    names = set()
    previous_threshold = None
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("cada nivel debe ser [umbral, nombre]")
        threshold, name = item
        if isinstance(threshold, bool) or not isinstance(threshold, int):
            raise ValueError("los umbrales deben ser enteros")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("los nombres de nivel no pueden estar vacíos")
        name = name.strip()
        if name in names:
            raise ValueError("los nombres de nivel deben ser únicos")
        if previous_threshold is not None and threshold <= previous_threshold:
            raise ValueError("los umbrales deben ser estrictamente crecientes")
        levels.append((threshold, name))
        names.add(name)
        previous_threshold = threshold
    return tuple(levels)


def _validate_date_scenes(value):
    if not isinstance(value, list) or not value:
        raise ValueError("se requiere una lista no vacía de escenas")
    scenes = []
    for scene in value:
        if not isinstance(scene, str) or not scene.strip():
            raise ValueError("las escenas deben ser cadenas no vacías")
        scene = scene.strip()
        if scene in scenes:
            raise ValueError("las escenas deben ser únicas")
        scenes.append(scene)
    return tuple(scenes)


def _validate_trait_allowlist(value):
    if not isinstance(value, list) or not value:
        raise ValueError("se requiere una lista no vacía de rasgos")
    traits = []
    for trait in value:
        if not isinstance(trait, str) or not trait.strip():
            raise ValueError("los rasgos deben ser cadenas no vacías")
        trait = trait.strip()
        if trait in traits:
            raise ValueError("los rasgos deben ser únicos")
        traits.append(trait)
    return tuple(traits)


def _validate_base_traits(value, allowlist, trait_min, trait_max):
    if not isinstance(value, dict) or set(value) != set(allowlist):
        raise ValueError("las claves deben coincidir con SELF_TRAITS_ALLOWLIST")
    for trait, score in value.items():
        if (
            not isinstance(trait, str)
            or not trait.strip()
            or isinstance(score, bool)
            or not isinstance(score, int)
            or not trait_min <= score <= trait_max
        ):
            raise ValueError("cada valor base debe ser un entero dentro del rango")
    return dict(value)


def _load_self_traits(default_allowlist, default_base, trait_min, trait_max):
    raw_allowlist = os.getenv("SELF_TRAITS_ALLOWLIST")
    raw_base = os.getenv("SELF_BASE_TRAITS")
    has_allowlist = raw_allowlist is not None and raw_allowlist.strip() != ""
    has_base = raw_base is not None and raw_base.strip() != ""
    if not has_allowlist and not has_base:
        return default_allowlist, default_base
    if not has_allowlist or not has_base:
        warnings.warn(
            "SELF_TRAITS_ALLOWLIST y SELF_BASE_TRAITS deben configurarse juntos; "
            "se usan los valores por defecto.",
            stacklevel=2,
        )
        return default_allowlist, default_base
    try:
        allowlist = _validate_trait_allowlist(json.loads(raw_allowlist))
        base = _validate_base_traits(
            json.loads(raw_base), allowlist, trait_min, trait_max
        )
        return allowlist, base
    except (TypeError, ValueError) as exc:
        warnings.warn(
            "SELF_TRAITS_ALLOWLIST/SELF_BASE_TRAITS no son válidos "
            f"({exc}); se usan los valores por defecto.",
            stacklevel=2,
        )
        return default_allowlist, default_base


def _positive_env_int(name, default, *, maximum=None):
    value = env_int(name, default)
    if value < 1 or (maximum is not None and value > maximum):
        bound = f" entre 1 y {maximum}" if maximum is not None else " positivo"
        warnings.warn(
            f"{name} debe ser un entero{bound}; se usa {default}.",
            stacklevel=2,
        )
        return default
    return value


# ============================================================
# CONSTANTES DE JUEGO
# ============================================================

_DEFAULT_AFFINITY_LEVELS = (
    (-100, "Bloqueada"),
    (-50, "Enfadada"),
    (-20, "Molesta"),
    (-1, "Distante"),
    (0, "Desconocida"),
    (10, "Conocida"),
    (25, "Amiga"),
    (45, "Cercana"),
    (70, "Muy cercana"),
    (100, "Inseparables"),
)
AFFINITY_LEVELS = _json_env(
    "AFFINITY_LEVELS", _DEFAULT_AFFINITY_LEVELS, _validate_affinity_levels
)

CONFESS_THRESHOLD = env_int("CONFESS_THRESHOLD", 100)  # Techo de afinidad/elegibilidad.
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

_DEFAULT_DATE_SCENES = (
    "un paseo por el parque al atardecer",
    "una tarde en una cafetería acogedora",
    "una sesión de cine con palomitas",
    "un día en la playa",
    "una cena a la luz de las velas",
    "una feria con luces de colores",
)
DATE_SCENES = _json_env("DATE_SCENES", _DEFAULT_DATE_SCENES, _validate_date_scenes)
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
# La IA decide si y cuándo hacerla; no existe turno forzado ni pregunta de
# reserva (la cita puede terminar sin pregunta).
DATE_QUESTION_MIN_TURNS = env_int("DATE_QUESTION_MIN_TURNS", 1)  # Turnos mínimos previos.
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
# ESCUCHA PASIVA (modo espectador): buffer, disparadores locales
# y política de intervención espontánea.
# ============================================================
AIRI_SPECTATOR_ENABLED = env_flag("AIRI_SPECTATOR_ENABLED", False)
AIRI_SPECTATOR_BUFFER_MAX = env_int("AIRI_SPECTATOR_BUFFER_MAX", 20)
AIRI_SPECTATOR_TTL_SECONDS = env_int("AIRI_SPECTATOR_TTL_SECONDS", 1800)
AIRI_SPECTATOR_AFFINITY_POINTS = env_int("AIRI_SPECTATOR_AFFINITY_POINTS", 20)
AIRI_SPECTATOR_PROB_TOPIC = env_float("AIRI_SPECTATOR_PROB_TOPIC", 0.55)
AIRI_SPECTATOR_PROB_AFFINITY = env_float("AIRI_SPECTATOR_PROB_AFFINITY", 0.35)
AIRI_SPECTATOR_COOLDOWN_SECONDS = env_int("AIRI_SPECTATOR_COOLDOWN_SECONDS", 300)
AIRI_SPECTATOR_SNAPSHOT_MAX = env_int("AIRI_SPECTATOR_SNAPSHOT_MAX", 12)
# Turno rápido: mensajes cortos sin web ni cita usan un contrato de salida
# reducido, menos historial y un tope de salida bajo para responder antes.
QUICK_REPLY_MAX_CHARS = env_int("QUICK_REPLY_MAX_CHARS", 60)
QUICK_HISTORY_MESSAGES = env_int("QUICK_HISTORY_MESSAGES", 6)
LLM_SHORT_MAX_TOKENS = env_int("LLM_SHORT_MAX_TOKENS", 400)

# ============================================================
# IDENTIDAD DE AIRI (self model)
# ============================================================
SELF_TRAIT_MIN = env_int("SELF_TRAIT_MIN", 1)
SELF_TRAIT_MAX = env_int("SELF_TRAIT_MAX", 5)
_DEFAULT_SELF_TRAITS_ALLOWLIST = (
    "expresiva",
    "timida",
    "juguetona",
    "celosa",
    "sarcastica",
    "curiosa",
)
_DEFAULT_SELF_BASE_TRAITS = {
    "expresiva": 4,
    "timida": 3,
    "juguetona": 5,
    "celosa": 2,
    "sarcastica": 2,
    "curiosa": 4,
}
SELF_TRAITS_ALLOWLIST, SELF_BASE_TRAITS = _load_self_traits(
    _DEFAULT_SELF_TRAITS_ALLOWLIST,
    _DEFAULT_SELF_BASE_TRAITS,
    SELF_TRAIT_MIN,
    SELF_TRAIT_MAX,
)
#: Instantánea de los valores fijados en el código (antes de leer el env).
#: Referencia para migrar identidades antiguas: sus rasgos absolutos se
#: interpretaron como "este baseline sin desviaciones aprendidas".
LEGACY_SELF_BASE_TRAITS = dict(_DEFAULT_SELF_BASE_TRAITS)
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
SELF_KEY_DAILY_LIMIT = _positive_env_int(
    "SELF_KEY_DAILY_LIMIT", 1, maximum=SELF_HISTORY_MAX
)
SELF_KEY_DAILY_SECONDS = env_int("SELF_KEY_DAILY_SECONDS", 86400)
SELF_DECAY_DAYS = env_int("SELF_DECAY_DAYS", 7)
SELF_DECAY_STEP = env_int("SELF_DECAY_STEP", 1)
SELF_REFLECTION_EVERY_N = env_int("SELF_REFLECTION_EVERY_N", 10)
SELF_REFLECTION_MIN_INTERVAL = env_int("SELF_REFLECTION_MIN_INTERVAL", 3600)
SELF_REFLECTION_MAX_TOKENS = env_int("SELF_REFLECTION_MAX_TOKENS", 300)
SELF_UPDATE_OPS = ("add", "remove", "inc", "set", "rewrite_concept", "none")
SELF_UPDATE_SOURCES = ("message", "gift", "date", "reflection", "season")
