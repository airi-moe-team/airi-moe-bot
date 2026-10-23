"""Modo espectador: detonantes locales y matcher de temas (puro, sin I/O).

La escucha pasiva añade al ciclo actual una regla de bajo coste: Airi lee el
canal sin llamar al LLM y solo despierta cuando (a) la mencionan o le responden,
(b) el mensaje toca un gusto positivo de su perfil, o (c) su autor alcanza un
umbral de afinidad. Interés y afinidad son señales INDEPENDIENTES: cualquiera de
ellas basta por sí sola para evaluar una intervención, aunque esta puede quedar
silentada por la tirada de probabilidad o por un cooldown activo.

Todo lo de este módulo es puro: no toca Discord, ni estado persistido, ni red.
Las probabilidades y umbrales llegan como argumentos (`AiriSpectatorPolicy`), de
modo que los tests puedan inyectarlos con valores deterministas.
"""

from __future__ import annotations

import json
import os
import re
import string
from dataclasses import dataclass

from airi.domain.constants import (
    AIRI_SPECTATOR_AFFINITY_POINTS,
    AIRI_SPECTATOR_BUFFER_MAX,
    AIRI_SPECTATOR_COOLDOWN_SECONDS,
    AIRI_SPECTATOR_HANDOFF_SECONDS,
    AIRI_SPECTATOR_PROB_AFFINITY,
    AIRI_SPECTATOR_PROB_TOPIC,
    AIRI_SPECTATOR_SNAPSHOT_MAX,
    AIRI_SPECTATOR_TTL_SECONDS,
)

_RAZON_MENCION = "mention"
_RAZON_TEMA = "topic"
_RAZON_AFINIDAD = "affinity"
_RAZON_HANDOFF = "handoff"

_MIN_LONGITUD_TERMINO = 3
_TEXTO_VACIO = ("", "none", "ninguno", "null", "n/a")


# ============================================================
# Configuración declarativa
# ============================================================


@dataclass(frozen=True)
class AiriSpectatorPolicy:
    """Política de modo espectador (efectiva; se recalcula del env)."""

    enabled: bool = False
    affinity_threshold: int = AIRI_SPECTATOR_AFFINITY_POINTS
    probability_topic: float = AIRI_SPECTATOR_PROB_TOPIC
    probability_affinity: float = AIRI_SPECTATOR_PROB_AFFINITY
    cooldown_seconds: int = AIRI_SPECTATOR_COOLDOWN_SECONDS
    snapshot_max_messages: int = AIRI_SPECTATOR_SNAPSHOT_MAX
    buffer_max: int = AIRI_SPECTATOR_BUFFER_MAX
    ttl_seconds: int = AIRI_SPECTATOR_TTL_SECONDS
    handoff_seconds: int = AIRI_SPECTATOR_HANDOFF_SECONDS


def load_policy(env=None):
    """Construye la política desde variables de entorno (sin estado global)."""
    getter = (
        (env or os.environ).get
        if env is None or hasattr(env, "get")
        else os.environ.get
    )
    if env is not None and not hasattr(env, "get"):
        raise TypeError("env debe ser un mapping o None")

    def _flag(name, default=True):
        raw = getter(name)
        if raw is None or raw.strip() == "":
            return default
        value = raw.strip().lower()
        if value in ("1", "true", "yes", "on"):
            return True
        if value in ("0", "false", "no", "off"):
            return False
        return default

    def _int(name, default):
        raw = getter(name)
        try:
            return int(raw) if raw and raw.strip() != "" else default
        except (TypeError, ValueError):
            return default

    def _float(name, default):
        raw = getter(name)
        try:
            return float(raw) if raw and raw.strip() != "" else default
        except (TypeError, ValueError):
            return default

    return AiriSpectatorPolicy(
        enabled=_flag("AIRI_SPECTATOR_ENABLED", default=False),
        affinity_threshold=_int("AIRI_SPECTATOR_AFFINITY_POINTS", AIRI_SPECTATOR_AFFINITY_POINTS),
        probability_topic=_float("AIRI_SPECTATOR_PROB_TOPIC", AIRI_SPECTATOR_PROB_TOPIC),
        probability_affinity=_float("AIRI_SPECTATOR_PROB_AFFINITY", AIRI_SPECTATOR_PROB_AFFINITY),
        cooldown_seconds=_int("AIRI_SPECTATOR_COOLDOWN_SECONDS", AIRI_SPECTATOR_COOLDOWN_SECONDS),
        snapshot_max_messages=_int("AIRI_SPECTATOR_SNAPSHOT_MAX", AIRI_SPECTATOR_SNAPSHOT_MAX),
        buffer_max=_int("AIRI_SPECTATOR_BUFFER_MAX", AIRI_SPECTATOR_BUFFER_MAX),
        ttl_seconds=_int("AIRI_SPECTATOR_TTL_SECONDS", AIRI_SPECTATOR_TTL_SECONDS),
        handoff_seconds=_int("AIRI_SPECTATOR_HANDOFF_SECONDS", AIRI_SPECTATOR_HANDOFF_SECONDS),
    )


@dataclass(frozen=True)
class ActivationDecision:
    """Resultado de evaluar las señales del modo espectador."""

    proceed: bool
    reason: str | None = None
    guaranteed: bool = False
    probability: float = 0.0
    roll: float = 0.0


# ============================================================
# Perfil canónico de gustos (estable) configurable por entorno
# ============================================================

_PROFILE_KEYS = ("loves", "dislikes", "favorite_food", "favorite_flower")


def _clean_profile(raw):
    """Normaliza un perfil de gustos: listas limpias y strings acotados."""
    if not isinstance(raw, dict):
        return None
    cleaned = {}
    had_content = False
    for key in _PROFILE_KEYS:
        value = raw.get(key)
        if isinstance(value, list):
            items = []
            for item in value:
                if isinstance(item, (dict, list, tuple, set)):
                    continue
                text = _clean_term(item)
                if text and not text.isdigit():
                    items.append(text)
            cleaned[key] = items
        elif isinstance(value, str):
            cleaned[key] = _clean_term(value)
        else:
            cleaned[key] = []
        if cleaned[key]:
            had_content = True
    if not had_content:
        return None
    return cleaned


def load_stable_profile(env=None):
    """Lee el perfil canónico de gustos desde `AIRI_PROFILE` (JSON).

    Devuelve None si la variable no está, está vacía, es JSON inválido o no
    contiene datos utilizables (el llamador entonces hace fallback al perfil
    persistido o a los defaults).
    """
    raw = (env or os.environ).get("AIRI_PROFILE")
    if raw is None or raw.strip() == "":
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return _clean_profile(data)


def apply_stable_profile(state, profile):
    """Persiste el perfil canónico de gustos en `world["preferences"]`.

    La persistencia es I/O del estado: vive en servicios, no en el dominio.
    Devuelve True si el estado cambió; un perfil vacío/None no toca nada.
    """
    from airi.domain.spectator import _clean_profile

    if not profile:
        return False
    cleaned = _clean_profile(profile) or {}
    if not cleaned:
        return False
    state.world["preferences"] = cleaned
    state.save_world()
    return True


# ============================================================
# Perfil de gustos y matcher de temas
# ============================================================


def _clean_term(value, max_chars=64):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split()).strip()
    return text[:max_chars]


def _profile_tastes(profile):
    """Devuelve el dict de gustos desde un modelo self, world o preferencias."""
    if not isinstance(profile, dict):
        return {}
    tastes = profile.get("tastes")
    if isinstance(tastes, dict):
        return tastes
    # `world["preferences"]` legacy y modelos antiguos exponen las claves arriba.
    if "loves" in profile or "favorite_food" in profile or "loves" in profile:
        return {
            "loves": profile.get("loves"),
            "dislikes": profile.get("dislikes"),
            "favorite_food": profile.get("favorite_food"),
            "favorite_flower": profile.get("favorite_flower"),
        }
    return {}


def positive_taste_terms(profile):
    """Términos positivos del perfil: loves + scalar favorites (sin dislikes).

    Las frases se parten en palabras para que "postres y dulces" active con
    "postres"; se descartan términos demasiado cortos o vacíos.
    """
    tastes = _profile_tastes(profile)
    terms = list(tastes.get("loves") or [])
    for key in ("favorite_food", "favorite_flower"):
        value = _clean_term(tastes.get(key))
        if value:
            terms.append(value)
    lowered = []
    for term in terms:
        clean = _clean_term(term)
        if not clean or clean.lower() in _TEXTO_VACIO:
            continue
        for word in clean.split():
            word = word.strip().strip(string.punctuation).lower()
            if len(word) >= _MIN_LONGITUD_TERMINO and word not in _TEXTO_VACIO:
                lowered.append(word)
    # Dedup estable.
    seen = set()
    ordered = []
    for term in lowered:
        if term not in seen:
            seen.add(term)
            ordered.append(term)
    return ordered


def build_topic_matcher(terms, aliases=()):
    """Compila una regex con límites de palabra a partir de los términos.

    Los alias deben declararse explícitamente (no se infieren). Devuelve None
    si no hay nada que buscar, para que el llamador salga en coste O(0).
    """
    candidates = []
    for term in (*(terms or []), *(aliases or [])):
        cleaned = _clean_term(term)
        if not cleaned or cleaned.lower() in _TEXTO_VACIO:
            continue
        lowered = cleaned.lower()
        # Las frases se pueden reconocer igual por alguna de sus piezas.
        candidates.append(re.escape(lowered))
        for word in lowered.split():
            if word and word not in _TEXTO_VACIO:
                candidates.append(re.escape(word))
    if not candidates:
        return None
    pattern = "|".join(sorted(set(candidates)))
    # Asume Python 3.11+ (pyproject), casefold innecesario.
    return re.compile(r"(?<!\w)(" + pattern + r")(?!\w)", re.IGNORECASE)


def _strip_punctuations(text):
    return text.strip().strip(string.punctuation)


def topic_eligible(pattern, text):
    """True si el texto cruza el matcher. Sin patrón => False (O(0))."""
    if pattern is None or not text:
        return False
    normalized = " ".join(str(text).split())
    return pattern.search(normalized) is not None


# ============================================================
# Señales de mención y afinidad
# ============================================================


def _clean_string(value, max_chars=120):
    if not isinstance(value, str):
        return ""
    return value.strip().lower()[:max_chars]


def mention_signals(content, airi_id, airi_name, is_reply_to_airi=False):
    """True si hay mención directa, respuesta a Airi o el nombre aparece.

    El nombre exige frontera de palabra para descartar palabras que lo
    contienen de casualidad (por ejemplo "chiari" o "sairi").
    """
    uid = str(airi_id or "")
    if is_reply_to_airi:
        return True
    text = str(content or "").lower()
    if not uid or not text:
        return False
    if f"<@{uid}>" in text or f"<@!{uid}>" in text:
        return True
    name = _clean_string(airi_name)
    if name in ("", "none", "ninguno"):
        return False
    name_pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)")
    return bool(name_pattern.search(text))


def affinity_eligible(points, threshold):
    """True si los puntos alcanzan el umbral configurable."""
    try:
        return int(points) >= int(threshold)
    except (TypeError, ValueError):
        return False


# ============================================================
# Decisión de activación
# ============================================================


def _combination_probability(topic, affinity, policy):
    """Interés y afinidad SON INDEPENDIENTES: cualquiera puede activar.

    Si ambas señales coinciden se usa el máximo de sus probabilidades, porque
    el estímulo doble merece como mucho la vía de mayor frecuencia.
    """
    probabilities = []
    if topic:
        probabilities.append(policy.probability_topic)
    if affinity:
        probabilities.append(policy.probability_affinity)
    if not probabilities:
        return None
    return max(probabilities)


def decide_activation(*, mention, topic, affinity, roll, policy, handoff=False):
    """Compone señales y tirada local en una decisión pura.

    Orden garantizado: (1) mención explícita, (2) handoff —respuesta del
    interlocutor a quien Airi acaba de preguntar—, (3) tema/afinidad con
    tirada local previa al LLM.
    """
    if not policy.enabled:
        return ActivationDecision(proceed=False, reason=None, guaranteed=False, roll=float(roll))
    if mention:
        return ActivationDecision(
            proceed=True, reason=_RAZON_MENCION, guaranteed=True, roll=float(roll)
        )
    if handoff:
        return ActivationDecision(
            proceed=True, reason=_RAZON_HANDOFF, guaranteed=True, roll=float(roll)
        )
    probability = _combination_probability(topic, affinity, policy)
    if probability is None:
        return ActivationDecision(proceed=False, reason=None, roll=float(roll))
    reason = _RAZON_TEMA if topic else _RAZON_AFINIDAD
    if affinity and not topic:
        reason = _RAZON_AFINIDAD
    elif topic and affinity:
        reason = _RAZON_TEMA
    numeric_roll = float(roll)
    proceed = numeric_roll < probability
    return ActivationDecision(
        proceed=proceed,
        reason=reason if proceed else reason,
        guaranteed=False,
        probability=float(probability),
        roll=numeric_roll,
    )


# Aliases de importación para poder pensar en la API con nombres estables.
__all__ = [
    "AiriSpectatorPolicy",
    "ActivationDecision",
    "affinity_eligible",
    "apply_stable_profile",
    "build_topic_matcher",
    "decide_activation",
    "load_policy",
    "load_stable_profile",
    "mention_signals",
    "positive_taste_terms",
    "topic_eligible",
]
