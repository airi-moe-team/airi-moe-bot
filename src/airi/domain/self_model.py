"""Modelo de identidad de Airi: la banda maleable de su "yo" (puro).

El núcleo inmutable de Airi (nombre, rol, honestidad anti-alucinación, idioma,
prohibición de emojis y contrato JSON) vive en `SYSTEM_PROMPT` y NO se toca
desde aquí. Este módulo gobierna la banda que Airi sí puede reescribir con
guardarraíles: auto-concepto, rasgos, valores, manías y gustos.

Diseño (resumen):

- `world["self"]` se siembra de forma perezosa y compatible con el
  `world["preferences"]` antiguo (`migrate_from_world`).
- Todos los cambios pasan por `apply_self_update`, que impone:
    * allowlist de claves mutables,
    * clamps (rasgos 1..5) y topes (listas, longitudes),
    * motivo + evidencia obligatorios (mismo candado que `affinity_event`),
    * rate-limit (≤ 1 cambio por clave/día + intervalo mínimo entre cambios),
    * registro auditable en `self["history"]`.
- `apply_decay` introduce una deriva lenta hacia los valores base.
- `should_reflect` decide cuándo toca una reflexión introspectiva.

Sin I/O: todo se hace sobre dicts.
"""

from __future__ import annotations

from airi.domain.affinity import default_preferences
from airi.domain.constants import (
    SELF_BASE_TRAITS,
    SELF_CONCEPT_MAX_CHARS,
    SELF_DECAY_DAYS,
    SELF_DECAY_STEP,
    SELF_DISCOVERIES_MAX,
    SELF_DISCOVERY_MAX_CHARS,
    SELF_HISTORY_MAX,
    SELF_KEY_DAILY_SECONDS,
    SELF_MAX_QUIRKS,
    SELF_MAX_TASTES,
    SELF_MAX_VALUES,
    SELF_QUIRK_MAX_CHARS,
    SELF_REFLECTION_EVERY_N,
    SELF_REFLECTION_MIN_INTERVAL,
    SELF_TASTE_MAX_CHARS,
    SELF_TRAIT_MAX,
    SELF_TRAIT_MIN,
    SELF_TRAITS_ALLOWLIST,
    SELF_UPDATE_MIN_INTERVAL,
    SELF_UPDATE_OPS,
    SELF_UPDATE_SOURCES,
    SELF_VALUE_MAX_CHARS,
)

# Prefijo de las claves de rasgo ("traits.juguetona").
SELF_TRAIT_PREFIX = "traits."

# Claves de lista (operaciones add/remove) y escalares (operación set).
SELF_LIST_KEYS = ("values", "quirks", "tastes.loves", "tastes.dislikes")
SELF_SCALAR_KEYS = ("tastes.favorite_flower", "tastes.favorite_food")
SELF_CONCEPT_KEY = "self_concept"

# Topes y longitud por clave de lista.
_LIST_LIMITS = {
    "values": (SELF_MAX_VALUES, SELF_VALUE_MAX_CHARS),
    "quirks": (SELF_MAX_QUIRKS, SELF_QUIRK_MAX_CHARS),
    "tastes.loves": (SELF_MAX_TASTES, SELF_TASTE_MAX_CHARS),
    "tastes.dislikes": (SELF_MAX_TASTES, SELF_TASTE_MAX_CHARS),
}

_NONE_WORDS = ("", "none", "ninguno", "null", "n/a")

# Esquema JSON del sub-objeto `self_update` (estricto: todas las props en
# `required`). `value` es siempre string en el contrato; el parseo convierte a
# entero cuando la operación lo requiere.
SELF_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "key": {"type": "string"},
        "op": {"type": "string", "enum": list(SELF_UPDATE_OPS)},
        "value": {"type": "string"},
        "reason": {"type": "string"},
        "evidence": {"type": "string"},
    },
    "required": ["key", "op", "value", "reason", "evidence"],
    "additionalProperties": False,
}


def self_update_none():
    """Forma canónica de "sin cambio" para el contrato JSON."""
    return {"key": "none", "op": "none", "value": "", "reason": "", "evidence": ""}


# ============================================================
# Utilidades internas (puras)
# ============================================================


def _clean_str(value, max_chars):
    if isinstance(value, bool):
        return ""
    if not isinstance(value, str):
        if isinstance(value, (int, float)):
            value = str(value)
        else:
            return ""
    text = " ".join(value.split()).strip()
    return text[:max_chars]


def _valid_reason(text):
    return bool(text) and text.strip().lower() not in _NONE_WORDS


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_list(items, cap, max_chars):
    if not isinstance(items, (list, tuple)):
        return []
    out = []
    for item in items:
        text = _clean_str(item, max_chars)
        if text and text not in out:
            out.append(text)
        if len(out) >= cap:
            break
    return out


def clamp_trait(value):
    """Acota un rasgo al rango [SELF_TRAIT_MIN, SELF_TRAIT_MAX]."""
    return max(SELF_TRAIT_MIN, min(SELF_TRAIT_MAX, _as_int(value, SELF_TRAIT_MIN)))


def _default_tastes(preferences):
    prefs = preferences if isinstance(preferences, dict) else default_preferences()
    return {
        "loves": _clean_list(
            prefs.get("loves"), SELF_MAX_TASTES, SELF_TASTE_MAX_CHARS
        ),
        "dislikes": _clean_list(
            prefs.get("dislikes"), SELF_MAX_TASTES, SELF_TASTE_MAX_CHARS
        ),
        "favorite_flower": _clean_str(
            prefs.get("favorite_flower"), SELF_TASTE_MAX_CHARS
        ),
        "favorite_food": _clean_str(prefs.get("favorite_food"), SELF_TASTE_MAX_CHARS),
    }


# ============================================================
# Semilla / migración / normalización
# ============================================================


def default_self(preferences=None):
    """Identidad inicial de Airi (absorbe los gustos de `preferences`)."""
    return {
        "version": 1,
        "self_concept": "",
        "traits": {name: int(SELF_BASE_TRAITS[name]) for name in SELF_TRAITS_ALLOWLIST},
        "values": [],
        "quirks": [],
        "tastes": _default_tastes(preferences),
        # `discoveries` ya NO forma parte del modelo global (decisión A5):
        # el aprendizaje libre vive en el ámbito privado del servidor.
        "history": [],
        # Relojes internos (no se muestran en el prompt).
        "last_decay_at": 0.0,
        "last_reflection_at": 0.0,
    }


def migrate_from_world(world):
    """Crea el `self` desde el mundo antiguo, o normaliza el existente.

    Si `world` ya trae `self`, ese manda (se normaliza y se devuelve). Si no, se
    siembra desde `world["preferences"]` para no perder los gustos ya fijados.
    """
    if isinstance(world, dict) and isinstance(world.get("self"), dict):
        return normalize_self(world["self"])
    preferences = world.get("preferences") if isinstance(world, dict) else None
    return default_self(preferences)


def normalize_self(model):
    """Sanea `model` en el sitio y garantiza la forma canónica. Devuelve `model`."""
    if not isinstance(model, dict):
        model = {}

    model["version"] = int(_as_int(model.get("version"), 1) or 1)

    # Rasgos: solo la allowlist, siempre presentes y acotados.
    raw_traits = model.get("traits")
    if not isinstance(raw_traits, dict):
        raw_traits = {}
    model["traits"] = {
        name: clamp_trait(raw_traits.get(name, SELF_BASE_TRAITS[name]))
        for name in SELF_TRAITS_ALLOWLIST
    }

    model["self_concept"] = _clean_str(
        model.get("self_concept"), SELF_CONCEPT_MAX_CHARS
    )
    model["values"] = _clean_list(
        model.get("values"), SELF_MAX_VALUES, SELF_VALUE_MAX_CHARS
    )
    model["quirks"] = _clean_list(
        model.get("quirks"), SELF_MAX_QUIRKS, SELF_QUIRK_MAX_CHARS
    )

    raw_tastes = model.get("tastes")
    if not isinstance(raw_tastes, dict):
        raw_tastes = {}
    default_tastes = _default_tastes(None)
    model["tastes"] = {
        "loves": _clean_list(
            raw_tastes.get("loves"), SELF_MAX_TASTES, SELF_TASTE_MAX_CHARS
        ),
        "dislikes": _clean_list(
            raw_tastes.get("dislikes"), SELF_MAX_TASTES, SELF_TASTE_MAX_CHARS
        ),
        "favorite_flower": _clean_str(
            raw_tastes.get("favorite_flower") or default_tastes["favorite_flower"],
            SELF_TASTE_MAX_CHARS,
        ),
        "favorite_food": _clean_str(
            raw_tastes.get("favorite_food") or default_tastes["favorite_food"],
            SELF_TASTE_MAX_CHARS,
        ),
    }

    # Descubrimientos (FIFO) — LECTURA HEREDADA (decisión A5).
    # El modelo global ya NO crea la clave: los descubrimientos libres viven
    # en el ámbito privado del servidor (`domain/self_notes.py`). Si una
    # identidad antigua trae la clave, se conserva tal cual para poder
    # reubicarla (no se escribe nunca en `identity.json`).
    if "discoveries" in model:
        raw_disc = model.get("discoveries")
        if not isinstance(raw_disc, list):
            raw_disc = []
        discoveries = []
        for item in raw_disc:
            if not isinstance(item, dict):
                continue
            text = _clean_str(item.get("text"), SELF_DISCOVERY_MAX_CHARS)
            if not text:
                continue
            discoveries.append(
                {
                    "ts": float(item.get("ts", 0.0) or 0.0),
                    "text": text,
                    "source": _clean_str(item.get("source"), 40) or "reflection",
                }
            )
        model["discoveries"] = discoveries[-SELF_DISCOVERIES_MAX:]

    # Historial (FIFO) de cambios auditables.
    raw_history = model.get("history")
    if not isinstance(raw_history, list):
        raw_history = []
    model["history"] = [e for e in raw_history if isinstance(e, dict)][
        -SELF_HISTORY_MAX:
    ]

    model["last_decay_at"] = float(model.get("last_decay_at", 0.0) or 0.0)
    model["last_reflection_at"] = float(model.get("last_reflection_at", 0.0) or 0.0)
    return model


# ============================================================
# Guardarraíles de mutación
# ============================================================


def _is_mutable_key(key):
    if key == SELF_CONCEPT_KEY:
        return True
    if key in SELF_LIST_KEYS or key in SELF_SCALAR_KEYS:
        return True
    if key.startswith(SELF_TRAIT_PREFIX):
        return key[len(SELF_TRAIT_PREFIX):] in SELF_TRAITS_ALLOWLIST
    return False


def is_mutable_key(key):
    """True si `key` es una clave que Airi puede reescribir de sí misma.

    Expuesto para que otros módulos (p. ej. la validación de identidad global)
    apliquen la MISMA allowlist y no la dupliquen.
    """
    return isinstance(key, str) and _is_mutable_key(key)


def _rate_limited(model, key, now):
    """True si un cambio de `key` en `now` viola el rate-limit."""
    history = [e for e in (model.get("history") or []) if isinstance(e, dict)]
    if not history:
        return False
    last_ts = float(history[-1].get("ts", 0.0) or 0.0)
    if last_ts and float(now) - last_ts < SELF_UPDATE_MIN_INTERVAL:
        return True
    same_key = [e for e in history if str(e.get("key")) == key]
    if same_key:
        ts = float(same_key[-1].get("ts", 0.0) or 0.0)
        if ts and float(now) - ts < SELF_KEY_DAILY_SECONDS:
            return True
    return False


def _get_list(model, key):
    if key == "values":
        return list(model.get("values") or [])
    if key == "quirks":
        return list(model.get("quirks") or [])
    tastes = model.get("tastes") or {}
    if key == "tastes.loves":
        return list(tastes.get("loves") or [])
    if key == "tastes.dislikes":
        return list(tastes.get("dislikes") or [])
    return []


def _compute_change(model, key, op, raw_value):
    """Devuelve (from, to) si la operación es válida; None si no cambia nada."""
    if key == SELF_CONCEPT_KEY:
        if op != "rewrite_concept":
            return None
        new = _clean_str(raw_value, SELF_CONCEPT_MAX_CHARS)
        old = model.get("self_concept", "")
        return (old, new) if new and new != old else None

    if key.startswith(SELF_TRAIT_PREFIX):
        name = key[len(SELF_TRAIT_PREFIX):]
        if name not in SELF_TRAITS_ALLOWLIST:
            return None
        current = model["traits"].get(name, SELF_BASE_TRAITS[name])
        if op == "inc":
            return (current, clamp_trait(current + _as_int(raw_value, 1)))
        if op == "set":
            return (current, clamp_trait(_as_int(raw_value, current)))
        if op == "add":
            return (current, clamp_trait(current + abs(_as_int(raw_value, 1))))
        return None

    if key in SELF_LIST_KEYS:
        cap, max_chars = _LIST_LIMITS[key]
        current = _get_list(model, key)
        item = _clean_str(raw_value, max_chars)
        if op == "add":
            if not item or item in current or len(current) >= cap:
                return None
            return (current, current + [item])
        if op == "remove":
            if not item or item not in current:
                return None
            return (current, [x for x in current if x != item])
        return None

    if key in SELF_SCALAR_KEYS:
        field = key.split(".", 1)[1]
        current = (model.get("tastes") or {}).get(field, "")
        if op == "set":
            new = _clean_str(raw_value, SELF_TASTE_MAX_CHARS)
            return (current, new) if new and new != current else None
        if op == "remove":
            return (current, "") if current else None
        return None

    return None


def _set_value(model, key, value):
    if key == SELF_CONCEPT_KEY:
        model["self_concept"] = value
    elif key.startswith(SELF_TRAIT_PREFIX):
        name = key[len(SELF_TRAIT_PREFIX):]
        if name in SELF_TRAITS_ALLOWLIST:
            model["traits"][name] = value
    elif key in ("values", "quirks"):
        model[key] = value
    elif key in ("tastes.loves", "tastes.dislikes"):
        model["tastes"][key.split(".", 1)[1]] = value
    elif key in SELF_SCALAR_KEYS:
        model["tastes"][key.split(".", 1)[1]] = value


def apply_self_update(model, update, *, now, user_id, source):
    """Aplica UN cambio de identidad juzgado por Airi. Devuelve la entrada o None.

    Devuelve `None` (sin tocar nada) si falta el motivo/evidencia, la clave no
    está en la allowlist, la operación no vale para esa clave, el cambio es
    nulo o el rate-limit lo bloquea.
    """
    normalize_self(model)
    if not isinstance(update, dict):
        return None

    key = update.get("key")
    op = update.get("op")
    if not isinstance(key, str) or not isinstance(op, str):
        return None
    key = key.strip()
    op = op.strip().lower()
    if op not in SELF_UPDATE_OPS or op == "none":
        return None
    if not key or key.lower() in _NONE_WORDS:
        return None
    if not _is_mutable_key(key):
        return None

    reason = _clean_str(update.get("reason"), 300)
    evidence = _clean_str(update.get("evidence"), 300)
    if not _valid_reason(reason) or not _valid_reason(evidence):
        return None

    if source not in SELF_UPDATE_SOURCES:
        source = "message"

    if _rate_limited(model, key, now):
        return None

    change = _compute_change(model, key, op, update.get("value", ""))
    if change is None:
        return None
    frm, to = change
    if frm == to:
        return None

    entry = {
        "ts": float(now),
        "key": key,
        "op": op,
        "value": _clean_str(update.get("value", ""), 200),
        "from": frm,
        "to": to,
        "reason": reason,
        "evidence": evidence,
        "user_id": str(user_id) if user_id is not None else "",
        "source": source,
    }
    _set_value(model, key, to)
    model["history"].append(entry)
    while len(model["history"]) > SELF_HISTORY_MAX:
        model["history"].pop(0)
    return entry


def revert_self_update(model, index, *, now=None):
    """Revierte el cambio nº `index` (1-based, orden cronológico).

    Restaura el valor `from` de esa entrada y deja constancia con una entrada
    `op="revert"`. Devuelve la entrada de reversión o None si el índice no vale.
    """
    normalize_self(model)
    history = model["history"]
    try:
        index = int(index)
    except (TypeError, ValueError):
        return None
    if not 1 <= index <= len(history):
        return None
    target = history[index - 1]
    key = target.get("key")
    if not isinstance(key, str) or not _is_mutable_key(key):
        return None
    frm = target.get("to")
    to = target.get("from")
    _set_value(model, key, to)
    entry = {
        "ts": float(now if now is not None else target.get("ts", 0.0) or 0.0),
        "key": key,
        "op": "revert",
        "value": f"revierte el cambio nº {index}",
        "from": frm,
        "to": to,
        "reason": "el dueño ha revertido este cambio",
        "evidence": f"revertido manualmente el cambio nº {index}",
        "user_id": str(target.get("user_id", "")),
        "source": "season",
    }
    history.append(entry)
    while len(history) > SELF_HISTORY_MAX:
        history.pop(0)
    return entry


# ============================================================
# Descubrimientos y decaimiento
# ============================================================
#
# El descobrimiento libre ya NO se escribe aquí (decisión A5): el único
# escritor es `domain/self_notes.py::add_note`, que guarda el aprendizaje en
# el ÁMBITO PRIVADO del servidor (`world["self_notes"]`).


def mark_reflection(model, now):
    """Sella el reloj de reflexión aunque la reflexión no produzca cambios."""
    normalize_self(model)
    model["last_reflection_at"] = float(now)


def should_reflect(
    *,
    interactions,
    model,
    now,
    force=False,
    every_n=SELF_REFLECTION_EVERY_N,
    min_interval=SELF_REFLECTION_MIN_INTERVAL,
):
    """True si toca una reflexión introspectiva (o si se fuerza)."""
    if force:
        return True
    try:
        count = int(interactions or 0)
    except (TypeError, ValueError):
        return False
    if count <= 0 or every_n <= 0 or count % every_n != 0:
        return False
    last = float((model or {}).get("last_reflection_at", 0.0) or 0.0)
    if last and float(now) - last < min_interval:
        return False
    return True


def apply_decay(model, now, *, days=SELF_DECAY_DAYS, step=SELF_DECAY_STEP):
    """Acerca poco a poco los rasgos a la base. Devuelve si cambió algo."""
    normalize_self(model)
    now = float(now)
    last = float(model.get("last_decay_at", 0.0) or 0.0)
    if not last:
        model["last_decay_at"] = now
        return False
    elapsed_days = int((now - last) // 86400)
    if elapsed_days < days or days <= 0:
        return False
    steps = max(1, (elapsed_days // days) * max(1, step))
    changed = False
    for name, base in SELF_BASE_TRAITS.items():
        current = model["traits"].get(name, base)
        if current > base:
            new = max(base, current - steps)
        elif current < base:
            new = min(base, current + steps)
        else:
            continue
        if new != current:
            model["traits"][name] = new
            changed = True
    model["last_decay_at"] = now
    return changed


# ============================================================
# Render (prompt y comando)
# ============================================================


def render_self_section(model, notes=None):
    """Cuerpo compacto del "yo" para el prompt (sin volcar el historial).

    `notes` son las notas privadas de Airi EN ESTE SERVIDOR (decisión A5): si
    no se pasan, se usan los `discoveries` del modelo (identidad antigua).
    """
    normalize_self(model)
    traits = ", ".join(
        f"{name} {model['traits'][name]}" for name in SELF_TRAITS_ALLOWLIST
    )
    lines = [
        f"Cómo me veo ahora mismo: {model['self_concept'] or '(todavía me estoy descubriendo)'}",
        f"Mis rasgos (1-5): {traits}",
    ]
    if model["values"]:
        lines.append("Lo que valoro: " + "; ".join(model["values"]))
    if model["quirks"]:
        lines.append("Mis manías: " + "; ".join(model["quirks"]))
    tastes = model["tastes"]
    lines.append(
        "Me encanta: "
        + (", ".join(tastes["loves"]) or "(nada fijado todavía)")
        + ". Me disgusta: "
        + (", ".join(tastes["dislikes"]) or "(nada fijado todavía)")
        + f". Mi flor favorita: {tastes['favorite_flower']}."
        + f" Mi comida favorita: {tastes['favorite_food']}."
    )
    if notes is None:
        recent = [e["text"] for e in (model.get("discoveries") or [])[-3:]]
    else:
        from airi.domain.self_notes import recent_notes

        recent = recent_notes(notes, 3)
    if recent:
        lines.append("Últimos descubrimientos sobre mí: " + " | ".join(recent))
    return "\n".join(lines)


def render_self_narrative(model, notes=None):
    """Resumen narrativo del "yo" para el comando público `!identidad-airi`.

    Los descubrimientos que se muestran son los privados de ESTE servidor
    (decisión A5): los de otros servidores no se comparten ni se consultan.
    """
    normalize_self(model)
    lines = []
    lines.append(
        "*Airi se queda pensando un momento en cómo se ve a sí misma...*\n"
        f"«{model['self_concept'] or 'Todavía me estoy descubriendo, ¿sabes?'}»"
    )
    traits = ", ".join(
        f"{name} {model['traits'][name]}/5" for name in SELF_TRAITS_ALLOWLIST
    )
    lines.append(f"**Mis rasgos:** {traits}")
    if model["values"]:
        lines.append("**Lo que valoro:** " + ", ".join(model["values"]))
    if model["quirks"]:
        lines.append("**Mis manías:** " + "; ".join(model["quirks"]))
    tastes = model["tastes"]
    lines.append(
        "**Mis gustos:** me encanta "
        + (", ".join(tastes["loves"]) or "(por descubrir)")
        + "; me disgusta "
        + (", ".join(tastes["dislikes"]) or "(por descubrir)")
        + f". Mi flor favorita son {tastes['favorite_flower']} y mi comida "
        + f"favorita es {tastes['favorite_food']}."
    )
    if notes is None:
        discoveries = list(model.get("discoveries") or [])
    else:
        from airi.domain.self_notes import normalize_notes

        discoveries = normalize_notes(notes)
    if discoveries:
        lines.append("**Lo último que he descubierto sobre mí:**")
        lines.extend(f"• {e['text']}" for e in discoveries[-3:])
    return "\n".join(lines)


def render_self_history(model):
    """Lista del historial de cambios (para `!identidad-airi historia`)."""
    normalize_self(model)
    lines = []
    for i, entry in enumerate(model.get("history") or [], start=1):
        ts = float(entry.get("ts", 0.0) or 0.0)
        try:
            ts_str = __import__("time").strftime("%Y-%m-%d %H:%M", __import__("time").localtime(ts))
        except Exception:
            ts_str = "desconocido"
        lines.append(
            f"{i}. {ts_str} — {entry.get('key')} ({entry.get('op')}): {entry.get('from')} → {entry.get('to')} — {entry.get('reason')}"
        )
    if not lines:
        return "Airi no ha cambiado nada de su forma de ser todavía."
    return "\n".join(lines[-10:])



def sync_preferences_from_self(world):
    """Mantiene `world["preferences"]` alineado con los gustos del self.

    La identidad es la fuente de verdad de los gustos, pero el resto del bot
    (regalos, prompt de preferencias) todavía lee `world["preferences"]`.
    """
    if not isinstance(world, dict):
        return
    model = normalize_self(world.get("self") or {})
    prefs = world.get("preferences")
    if not isinstance(prefs, dict):
        prefs = default_preferences()
        world["preferences"] = prefs
    tastes = model.get("tastes") or {}
    prefs["loves"] = list(tastes.get("loves") or [])
    prefs["dislikes"] = list(tastes.get("dislikes") or [])
    prefs["favorite_flower"] = str(tastes.get("favorite_flower") or "")
    prefs["favorite_food"] = str(tastes.get("favorite_food") or "")
