"""Modelo de identidad de Airi: la banda maleable de su "yo" (puro).

El núcleo inmutable de Airi (nombre, rol, honestidad anti-alucinación, idioma y
contrato JSON) vive en `SYSTEM_PROMPT` y NO se toca
desde aquí. Este módulo gobierna la banda que Airi sí puede reescribir con
guardarraíles: auto-concepto, rasgos, valores y manías.

Diseño (resumen):

- `world["self"]` se siembra de forma perezosa.
- Los gustos NO forman parte de este modelo: su única fuente canónica es
  `world["preferences"]` (configurable por `AIRI_PROFILE`).
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

from airi.domain.constants import (
    LEGACY_SELF_BASE_TRAITS,
    MOOD_BAR_WIDTH,
    SELF_BASE_TRAITS,
    SELF_CONCEPT_MAX_CHARS,
    SELF_DECAY_DAYS,
    SELF_DECAY_STEP,
    SELF_DISCOVERIES_MAX,
    SELF_DISCOVERY_MAX_CHARS,
    SELF_HISTORY_MAX,
    SELF_KEY_DAILY_LIMIT,
    SELF_KEY_DAILY_SECONDS,
    SELF_MAX_QUIRKS,
    SELF_MAX_VALUES,
    SELF_QUIRK_MAX_CHARS,
    SELF_REFLECTION_EVERY_N,
    SELF_REFLECTION_MIN_INTERVAL,
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

# Claves de lista (operaciones add/remove).
SELF_LIST_KEYS = ("values", "quirks")
SELF_CONCEPT_KEY = "self_concept"

# Topes y longitud por clave de lista.
_LIST_LIMITS = {
    "values": (SELF_MAX_VALUES, SELF_VALUE_MAX_CHARS),
    "quirks": (SELF_MAX_QUIRKS, SELF_QUIRK_MAX_CHARS),
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


# ============================================================
# Semilla / migración / normalización
# ============================================================


def default_self():
    """Identidad inicial de Airi (sin gustos: esos viven en preferences)."""
    return {
        "version": 1,
        "self_concept": "",
        "traits": {name: int(SELF_BASE_TRAITS[name]) for name in SELF_TRAITS_ALLOWLIST},
        # Aprendizaje como DESVIACIÓN respecto de la base del env: Airi evoluciona
        # sobre `SELF_BASE_TRAITS` y el decaimiento la lleva de vuelta a él.
        "traits_learned": {},
        # Instantánea del baseline con el que se creó/actualizó la identidad:
        # si el env cambia, `normalize_self` puede distinguir "cambió la base"
        # de "Airi aprendió algo" y migrar sin perder el personaje.
        "traits_base": dict(SELF_BASE_TRAITS),
        "values": [],
        "quirks": [],
        # `discoveries` ya NO forma parte del modelo global (decisión A5):
        # el aprendizaje libre vive en el ámbito privado del servidor.
        "history": [],
        # Relojes internos (no se muestran en el prompt).
        "last_decay_at": 0.0,
        "last_reflection_at": 0.0,
    }


def migrate_from_world(world):
    """Crea el `self` desde el mundo, o normaliza el existente.

    Los gustos ya no forman parte de la identidad mutable: su fuente canónica
    es `world["preferences"]` y no se copian aquí.
    """
    if isinstance(world, dict) and isinstance(world.get("self"), dict):
        return normalize_self(world["self"])
    return default_self()


def _normalize_learned(name, learned, base):
    """Acota la desviación aprendida para que base+learned siga en rango."""
    low = SELF_TRAIT_MIN - base
    high = SELF_TRAIT_MAX - base
    return max(low, min(high, _as_int(learned, 0)))


def _sum_history_delta(entries, name):
    """Suma `to - from` de las entradas auditables de un rasgo (puro)."""
    key = f"{SELF_TRAIT_PREFIX}{name}"
    delta = 0
    for entry in entries:
        if entry.get("key") != key:
            continue
        try:
            frm = int(entry["from"])
            to = int(entry["to"])
        except (KeyError, TypeError, ValueError):
            continue
        delta += to - frm
    return delta


def _has_trait_history(history):
    key_prefix = SELF_TRAIT_PREFIX
    for entry in history:
        key = entry.get("key")
        if isinstance(key, str) and key.startswith(key_prefix):
            return True
    return False


def _migrate_traits(model, raw_traits, stored_base):
    """Anota la desviación aprendida y la base efectiva en el modelo.

    Estrategia de migración (obedece al env y preserva lo aprendido):

    - Estado nuevo (`raw_traits` vacío) o identidad legado idéntica al
      baseline del código sin historial de rasgos: desviaciones 0 → los
      rasgos efectivos SON los de `SELF_BASE_TRAITS` (el env manda ya).
    - Con evidencia de aprendizaje en el historial auditable (entradas con
      `key="traits.<nombre>"`): se reconstruye la desviación sumando
      `to - from` por rasgo.
    - Legado con valores ajenos al baseline del código y sin historial: se
      asume edición manual y se recalcula la desviación (`valor - base
      nueva`) para que el valor efectivo NO cambie al reiniciar; el
      decaimiento posterior la lleva lentamente al nuevo baseline.

    Devuelve `(learned, fresh_seed)`; `fresh_seed=True` marca identidades
    recién sembradas cuya armonización con `raw` debe omitirse para que el
    baseline del env efectivice de una vez.
    """
    learned = {}
    if not raw_traits:
        return learned, True
    reference = dict(
        stored_base
        if isinstance(stored_base, dict)
        else LEGACY_SELF_BASE_TRAITS
    )
    history = [e for e in (model.get("history") or []) if isinstance(e, dict)]
    if _has_trait_history(history):
        for name in SELF_TRAITS_ALLOWLIST:
            base = int(SELF_BASE_TRAITS.get(name, 0))
            learned[name] = _normalize_learned(
                name, _sum_history_delta(history, name), base
            )
        return learned, False
    fresh_seed = not any(
        _as_int(raw_traits.get(name, reference.get(name, 0)), 0)
        != int(reference.get(name, 0))
        for name in raw_traits
        if isinstance(name, str) and name in SELF_TRAITS_ALLOWLIST
    )
    if fresh_seed:
        # Identidad recién sembrada con el baseline del código (sin ninguna
        # desviación aprendida): el env actual define el punto de partida.
        return learned, True
    for name in SELF_TRAITS_ALLOWLIST:
        base = int(SELF_BASE_TRAITS.get(name, 0))
        old = _as_int(raw_traits.get(name, reference.get(name, base)), base)
        learned[name] = _normalize_learned(name, old - base, base)
    return learned, False


def normalize_self(model):
    """Sanea `model` en el sitio y garantiza la forma canónica. Devuelve `model`."""
    if not isinstance(model, dict):
        model = {}

    model["version"] = int(_as_int(model.get("version"), 1) or 1)

    # Rasgos: solo la allowlist, siempre presentes y acotados. El valor
    # efectivo derive de la base del env + Aprendizaje (traits_learned); los
    # números absolutos antiguos se migran una vez (ver `_migrate_traits`).
    raw_traits = model.get("traits")
    if not isinstance(raw_traits, dict):
        raw_traits = {}
    stored_base = model.get("traits_base")
    baseline_changed = not isinstance(stored_base, dict) or dict(
        stored_base
    ) != dict(SELF_BASE_TRAITS)
    learned_raw = model.get("traits_learned")
    fresh_seed = False
    if isinstance(learned_raw, dict) and not baseline_changed:
        learned = {
            name: _normalize_learned(name, learned_raw.get(name, 0),
                                     int(SELF_BASE_TRAITS[name]))
            for name in SELF_TRAITS_ALLOWLIST
        }
    else:
        learned, fresh_seed = _migrate_traits(
            model, raw_traits, stored_base
        )

    # Armonización: un valor absoluto escrito por fuera (edit manual del
    # estado, test o versión previa) manda sobre la derivación; se re-anota
    # como aprendizaje para no perderlo en el próximo normalize. Se omite en
    # semillas recién migradas: el env debe efectivizar su baseline.
    if not fresh_seed:
        for name in SELF_TRAITS_ALLOWLIST:
            base = int(SELF_BASE_TRAITS[name])
            if name in raw_traits:
                raw_value = _as_int(raw_traits[name], base)
                if raw_value != clamp_trait(base + learned.get(name, 0)):
                    learned[name] = _normalize_learned(
                        name, raw_value - base, base
                    )

    model["traits_learned"] = learned
    model["traits_base"] = dict(SELF_BASE_TRAITS)
    model["traits"] = {
        name: clamp_trait(
            int(SELF_BASE_TRAITS[name]) + learned.get(name, 0)
        )
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

    # Los gustos son legado: la fuente canónica es `world["preferences"]`.
    # Se retiran del modelo al normalizar para que no queden listas duplicadas.
    model.pop("tastes", None)

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
    if key in SELF_LIST_KEYS:
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
    same_key_recent = 0
    for entry in history:
        if str(entry.get("key")) != key:
            continue
        try:
            timestamp = float(entry.get("ts", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if timestamp and float(now) - timestamp < SELF_KEY_DAILY_SECONDS:
            same_key_recent += 1
    return same_key_recent >= SELF_KEY_DAILY_LIMIT


def _get_list(model, key):
    if key == "values":
        return list(model.get("values") or [])
    if key == "quirks":
        return list(model.get("quirks") or [])
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

    return None


def _set_value(model, key, value):
    if key == SELF_CONCEPT_KEY:
        model["self_concept"] = value
    elif key.startswith(SELF_TRAIT_PREFIX):
        name = key[len(SELF_TRAIT_PREFIX):]
        if name in SELF_TRAITS_ALLOWLIST:
            model["traits"][name] = value
            base = int(SELF_BASE_TRAITS[name])
            learned = model.setdefault("traits_learned", {})
            learned[name] = _normalize_learned(name, _as_int(value, base) - base,
                                               base)
    elif key in ("values", "quirks"):
        model[key] = value


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
    """Acerca poco a poco los rasgos aprendidos a la base del env.

    El aprendizaje vive en `traits_learned` (desviaciones respecto de
    `SELF_BASE_TRAITS`); el decaimiento reduce esas desviaciones hacia 0, así
    que los rasgos efectivos regresan al baseline configurado.
    """
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
    learned = model["traits_learned"]
    for name in SELF_TRAITS_ALLOWLIST:
        offset = _as_int(learned.get(name, 0), 0)
        if offset == 0:
            continue
        new = offset - steps if offset > 0 else offset + steps
        # Nunca se pasa de 0: la base siempre es el destino final.
        if (offset > 0 and new < 0) or (offset < 0 and new > 0):
            new = 0
        learned[name] = new
        base = int(SELF_BASE_TRAITS[name])
        model["traits"][name] = clamp_trait(base + new)
        changed = True
    model["last_decay_at"] = now
    return changed


# ============================================================
# Render (prompt y comando)
# ============================================================


_TRAIT_GROUPS = (
    ("Expresividad", (("expresiva", 1), ("timida", -1))),
    ("Humor", (("juguetona", 1), ("sarcastica", 1))),
    ("Curiosidad", (("curiosa", 1),)),
    ("Reactividad", (("celosa", 1),)),
)


def render_trait_bars(traits, *, width=MOOD_BAR_WIDTH):
    """Resume traits en dimensiones amplias con barras de intensidad 1–5.

    Expresividad combina expresividad y timidez (invertida); Humor combina
    juego y sarcasmo. Los demás grupos conservan la intensidad de su trait.
    """
    values = traits if isinstance(traits, dict) else {}
    lines = []
    known = set()
    for label, members in _TRAIT_GROUPS:
        present = [(key, sign) for key, sign in members if key in values]
        if not present:
            continue
        group_values = []
        for key, sign in present:
            raw = clamp_trait(_as_int(values.get(key), SELF_TRAIT_MIN))
            known.add(key)
            group_values.append(raw if sign > 0 else SELF_TRAIT_MAX + SELF_TRAIT_MIN - raw)
        intensity = clamp_trait(round(sum(group_values) / len(group_values)))
        filled = max(0, min(width, round(intensity / SELF_TRAIT_MAX * width)))
        bar = "█" * filled + "░" * (width - filled)
        lines.append(f"{label:<18} {bar} {intensity}/{SELF_TRAIT_MAX}")

    # Los traits personalizados configurados por entorno siguen visibles.
    for name in SELF_TRAITS_ALLOWLIST:
        if name in known or name not in values:
            continue
        intensity = clamp_trait(_as_int(values.get(name), SELF_TRAIT_MIN))
        filled = max(0, min(width, round(intensity / SELF_TRAIT_MAX * width)))
        bar = "█" * filled + "░" * (width - filled)
        lines.append(f"{name.capitalize():<18} {bar} {intensity}/{SELF_TRAIT_MAX}")
    return "\n".join(lines)


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
    if notes is None:
        recent = [e["text"] for e in (model.get("discoveries") or [])[-3:]]
    else:
        from airi.domain.self_notes import recent_notes

        recent = recent_notes(notes, 3)
    if recent:
        lines.append("Últimos descubrimientos sobre mí: " + " | ".join(recent))
    return "\n".join(lines)


def preferences_view(preferences):
    """Gustos canónicos listos para mostrar (fuente: `world["preferences"]`)."""
    prefs = preferences if isinstance(preferences, dict) else {}
    return {
        "loves": list(prefs.get("loves") or []),
        "comforts": list(prefs.get("comforts") or []),
        "curious_about": list(prefs.get("curious_about") or []),
        "dislikes": list(prefs.get("dislikes") or []),
        "boundaries": list(prefs.get("boundaries") or []),
        "favorite_flower": str(prefs.get("favorite_flower") or ""),
        "favorite_food": str(prefs.get("favorite_food") or ""),
    }


def render_self_narrative(model, notes=None, preferences=None, mood=None):
    """Resumen narrativo del "yo" para el comando público `!identidad-airi`.

    Los descubrimientos que se muestran son los privados de ESTE servidor
    (decisión A5): los de otros servidores no se comparten ni se consultan.
    Los gustos se leen del perfil canónico (`world["preferences"]`).
    """
    from airi.domain.mood import normalize_mood, render_mood_meter

    normalize_self(model)
    lines = []
    lines.append(
        "*Airi se queda pensando un momento en cómo se ve a sí misma...*\n"
        f"«{model['self_concept'] or 'Todavía me estoy descubriendo, ¿sabes?'}»"
    )
    lines.append(f"**Mis rasgos:**\n{render_trait_bars(model['traits'])}")
    current_mood = normalize_mood(mood)
    if current_mood is not None:
        lines.append(
            f"**Mi ánimo ahora:** {render_mood_meter(current_mood)}"
        )
    if model["values"]:
        lines.append("**Lo que valoro:** " + ", ".join(model["values"]))
    if model["quirks"]:
        lines.append("**Mis manías:** " + "; ".join(model["quirks"]))
    tastes = preferences_view(preferences)
    lines.append(
        "**Mis intereses:** " + (", ".join(tastes["loves"]) or "(por descubrir)")
    )
    if tastes["comforts"]:
        lines.append("**Me reconforta:** " + ", ".join(tastes["comforts"]))
    if tastes["curious_about"]:
        lines.append("**Me da curiosidad:** " + ", ".join(tastes["curious_about"]))
    if tastes["dislikes"]:
        lines.append("**Prefiero evitar:** " + ", ".join(tastes["dislikes"]))
    if tastes["boundaries"]:
        lines.append("**Límites de trato:** " + ", ".join(tastes["boundaries"]))
    lines.append(
        f"**Preferencias registradas:** flor {tastes['favorite_flower'] or '(por descubrir)'}; "
        f"comida {tastes['favorite_food'] or '(por descubrir)'}."
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
