"""Ánimo transitorio de Airi por turno (puro).

Diseño (resumen):

- Los `traits` de `self_model` son la personalidad estable. El ánimo es una
  capa aparte que sí puede variar en cada turno y que se lee en el prompt y en
  la traza.
- El ánimo se declara en la salida del modelo (`mood`), se acota y se suaviza
  con inercia (`MOOD_MAX_STEP`) para evitar saltos bruscos entre mensajes.
- Si el modelo no lo declara, se usa una base determinista derivada de los
  traits y la hora (`baseline_mood`).
- `world["mood"]` guarda el ánimo vigente y `world["mood_history"]` la línea
  temporal reciente. El ánimo NUNCA modifica traits ni afinidad.
- El ánimo es global (el de Airi); la actitud hacia cada persona se deriva en
  el render combinándolo con la afinidad, sin persistirse por separado.

Sin I/O: todo se hace sobre dicts.
"""

from __future__ import annotations

import time
import unicodedata

from airi.domain.affinity import affinity_level, level_rank
from airi.domain.constants import (
    MOOD_AROUSAL_MAX,
    MOOD_AROUSAL_MIN,
    MOOD_BAR_WIDTH,
    MOOD_CATEGORY_MAX,
    MOOD_CATEGORY_MAX_VISIBLE,
    MOOD_CATEGORY_MIN_SECONDARY,
    MOOD_CAUSE_MAX_CHARS,
    MOOD_HISTORY_MAX,
    MOOD_MAX_STEP,
    MOOD_STALE_SECONDS,
    MOOD_VALENCE_MAX,
    MOOD_VALENCE_MIN,
)

#: Etiquetas cerradas del ánimo. El orden es también el orden de desempate al
#: derivar una etiqueta a partir de los ejes.
MOOD_LABELS = (
    "neutral",
    "alegre",
    "juguetona",
    "tranquila",
    "timida",
    "melancolica",
    "molesta",
    "curiosa",
)

#: Nombre visible (con acentos) de cada etiqueta.
MOOD_LABELS_ES = {
    "neutral": "Neutral",
    "alegre": "Alegre",
    "juguetona": "Juguetona",
    "tranquila": "Tranquila",
    "timida": "Tímida",
    "melancolica": "Melancólica",
    "molesta": "Molesta",
    "curiosa": "Curiosa",
}


def mood_label_display(label):
    """Nombre legible de una etiqueta de ánimo."""
    return MOOD_LABELS_ES.get(str(label), str(label).capitalize())


#: Categorías visibles del ánimo (cuatro cuadrantes + neutral). El orden es
#: también el de desempate cuando dos categorías empatan en intensidad.
MOOD_CATEGORIES = ("entusiasmo", "tension", "calma", "bajon", "neutral")

#: Nombre visible de cada categoría.
MOOD_CATEGORY_NAMES = {
    "entusiasmo": "Entusiasmo",
    "tension": "Tensión",
    "calma": "Calma",
    "bajon": "Bajón",
    "neutral": "Neutral",
}

#: Emoji de cada categoría (para sparklines y resúmenes).
MOOD_CATEGORY_EMOJI = {
    "entusiasmo": "🟡",
    "tension": "🔴",
    "calma": "🔵",
    "bajon": "⚫",
    "neutral": "⚪",
}

#: Color lateral del embed de cada categoría (entero 0xRRGGBB).
MOOD_CATEGORY_COLORS = {
    "entusiasmo": 0xF5C542,
    "tension": 0xE74C3C,
    "calma": 0x5DADE2,
    "bajon": 0x34495E,
    "neutral": 0x95A5A6,
}

#: Sinónimos tolerantes para las claves de categoría.
_CATEGORY_SYNONYMS = {
    "euforia": "entusiasmo",
    "motivacion": "entusiasmo",
    "alegria": "entusiasmo",
    "entusiasmo": "entusiasmo",
    "estres": "tension",
    "ansiedad": "tension",
    "ira": "tension",
    "frustracion": "tension",
    "tension": "tension",
    "serenidad": "calma",
    "satisfaccion": "calma",
    "relajacion": "calma",
    "calma": "calma",
    "tristeza": "bajon",
    "apatia": "bajon",
    "cansancio": "bajon",
    "aburrimiento": "bajon",
    "bajon": "bajon",
    "neutro": "neutral",
    "neutral": "neutral",
}


def mood_category_display(key):
    """Nombre legible de una categoría de ánimo."""
    return MOOD_CATEGORY_NAMES.get(str(key), str(key).capitalize())



#: Ejes canónicos de cada etiqueta: (valencia, energía, cercanía).
MOOD_AXES_BY_LABEL = {
    "neutral": (0, 3, 3),
    "alegre": (2, 4, 4),
    "juguetona": (2, 4, 3),
    "tranquila": (1, 2, 4),
    "timida": (0, 2, 3),
    "melancolica": (-2, 2, 2),
    "molesta": (-2, 3, 1),
    "curiosa": (1, 4, 3),
}

#: Esquema JSON del ánimo declarado por el modelo (estricto: todas las
#: propiedades en `required`, como `self_update`).
MOOD_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": list(MOOD_LABELS)},
        "valence": {"type": "integer"},
        "energy": {"type": "integer"},
        "warmth": {"type": "integer"},
        "categories": {
            "type": "object",
            "properties": {
                key: {"type": "integer"} for key in MOOD_CATEGORIES
            },
            "required": list(MOOD_CATEGORIES),
            "additionalProperties": False,
        },
        "cause": {"type": "string"},
    },
    "required": [
        "label",
        "valence",
        "energy",
        "warmth",
        "categories",
        "cause",
    ],
    "additionalProperties": False,
}

#: Sinónimos tolerantes que puede devolver el modelo.
_LABEL_SYNONYMS = {
    "feliz": "alegre",
    "contenta": "alegre",
    "animada": "alegre",
    "alegria": "alegre",
    "divertida": "juguetona",
    "graciosa": "juguetona",
    "bromista": "juguetona",
    "juego": "juguetona",
    "relajada": "tranquila",
    "calmada": "tranquila",
    "serena": "tranquila",
    "calma": "tranquila",
    "vergonzosa": "timida",
    "timidez": "timida",
    "triste": "melancolica",
    "tristeza": "melancolica",
    "bajon": "melancolica",
    "apenada": "melancolica",
    "enfadada": "molesta",
    "enfado": "molesta",
    "enojo": "molesta",
    "ira": "molesta",
    "irritada": "molesta",
    "frustrada": "molesta",
    "intrigada": "curiosa",
    "interesada": "curiosa",
    "curiosidad": "curiosa",
    "normal": "neutral",
}

_NONE_WORDS = ("", "none", "ninguno", "ninguna", "null", "n/a")


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, low, high):
    return max(low, min(high, _as_int(value, low)))


def _strip_accents(text):
    normalized = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_label(raw):
    """Devuelve una etiqueta canónica o `""` si no es reconocible."""
    if not isinstance(raw, str):
        return ""
    text = _strip_accents(raw).strip().lower()
    text = " ".join(text.replace("_", " ").split())
    if not text or text in _NONE_WORDS:
        return ""
    text = text.replace(" ", "")
    if text in MOOD_LABELS:
        return text
    return _LABEL_SYNONYMS.get(text, "")


def normalize_categories(raw):
    """Normaliza las intensidades por categoría a su forma canónica.

    Siempre devuelve las cinco claves (0..5). Acepta claves con acentos,
    espacios o sinónimos ("estrés" → "tension").
    """
    categories = {key: 0 for key in MOOD_CATEGORIES}
    if not isinstance(raw, dict):
        return categories
    for name, value in raw.items():
        key = _strip_accents(str(name)).strip().lower()
        key = key.replace("_", "").replace(" ", "")
        key = _CATEGORY_SYNONYMS.get(key, key)
        if key in categories:
            categories[key] = _clamp(value, 0, MOOD_CATEGORY_MAX)
    return categories


def categories_from_axes(valence, energy, warmth=3):
    """Deriva las intensidades de categoría a partir de los ejes.

    Se usa en la migración de ánimos antiguos (sin `categories`) y en el
    ánimo base. La intensidad de la categoría dominante crece con la energía;
    en el lado positivo de baja energía, la calma crece al bajar la energía.
    """
    v = _clamp(valence, MOOD_VALENCE_MIN, MOOD_VALENCE_MAX)
    e = _clamp(energy, MOOD_AROUSAL_MIN, MOOD_AROUSAL_MAX)
    categories = {key: 0 for key in MOOD_CATEGORIES}
    if v == 0:
        categories["neutral"] = 3
    elif v > 0:
        if e >= 3:
            categories["entusiasmo"] = e
        else:
            categories["calma"] = _clamp(3 + (3 - e), 1, MOOD_CATEGORY_MAX)
    else:
        if e >= 3:
            categories["tension"] = e
        else:
            categories["bajon"] = _clamp(3 + (3 - e), 1, MOOD_CATEGORY_MAX)
    return categories


def _has_categories(raw):
    if not isinstance(raw, dict):
        return False
    for name in raw:
        key = _strip_accents(str(name)).strip().lower()
        key = key.replace("_", "").replace(" ", "")
        if _CATEGORY_SYNONYMS.get(key, key) in MOOD_CATEGORIES:
            return True
    return False


def label_for_axes(valence, energy, warmth):
    """Etiqueta más cercana a unos ejes dados (distancia normalizada)."""
    v = _clamp(valence, MOOD_VALENCE_MIN, MOOD_VALENCE_MAX) / 2.0
    e = (_clamp(energy, MOOD_AROUSAL_MIN, MOOD_AROUSAL_MAX) - 3) / 2.0
    w = (_clamp(warmth, MOOD_AROUSAL_MIN, MOOD_AROUSAL_MAX) - 3) / 2.0
    best = MOOD_LABELS[0]
    best_distance = None
    for label in MOOD_LABELS:
        lv, le, lw = MOOD_AXES_BY_LABEL[label]
        distance = (
            (v - lv / 2.0) ** 2
            + (e - (le - 3) / 2.0) ** 2
            + (w - (lw - 3) / 2.0) ** 2
        )
        if best_distance is None or distance < best_distance:
            best = label
            best_distance = distance
    return best


def normalize_mood(raw):
    """Normaliza un ánimo propuesto. Devuelve `None` si no hay nada usable.

    Acepta un dict completo o una etiqueta suelta. Los ejes se acotan y, si
    faltan, se derivan de la etiqueta. La causa se limpia y se acota.
    """
    if isinstance(raw, str):
        label = normalize_label(raw)
        if not label:
            return None
        valence, energy, warmth = MOOD_AXES_BY_LABEL[label]
        return {
            "label": label,
            "valence": valence,
            "energy": energy,
            "warmth": warmth,
            "categories": categories_from_axes(valence, energy, warmth),
            "cause": "none",
            "updated_at": 0.0,
        }
    if not isinstance(raw, dict):
        return None

    label = normalize_label(raw.get("label"))
    has_axes = any(key in raw for key in ("valence", "energy", "warmth"))
    if not label and not has_axes:
        return None

    if label:
        base_valence, base_energy, base_warmth = MOOD_AXES_BY_LABEL[label]
    else:
        base_valence, base_energy, base_warmth = MOOD_AXES_BY_LABEL["neutral"]

    valence = _clamp(
        raw.get("valence", base_valence), MOOD_VALENCE_MIN, MOOD_VALENCE_MAX
    )
    energy = _clamp(
        raw.get("energy", base_energy), MOOD_AROUSAL_MIN, MOOD_AROUSAL_MAX
    )
    warmth = _clamp(
        raw.get("warmth", base_warmth), MOOD_AROUSAL_MIN, MOOD_AROUSAL_MAX
    )
    if not label:
        label = label_for_axes(valence, energy, warmth)

    if _has_categories(raw.get("categories")):
        categories = normalize_categories(raw.get("categories"))
    else:
        categories = categories_from_axes(valence, energy, warmth)

    cause_raw = raw.get("cause", "none")
    cause = ""
    if isinstance(cause_raw, str):
        cause = " ".join(cause_raw.split()).strip()[:MOOD_CAUSE_MAX_CHARS]
    if cause.lower() in _NONE_WORDS:
        cause = "none"

    try:
        updated_at = float(raw.get("updated_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        updated_at = 0.0

    return {
        "label": label,
        "valence": valence,
        "energy": energy,
        "warmth": warmth,
        "categories": categories,
        "cause": cause or "none",
        "updated_at": updated_at,
    }


def default_mood():
    """Ánimo neutro canónico (sin timestamps)."""
    return {
        "label": "neutral",
        "valence": 0,
        "energy": 3,
        "warmth": 3,
        "categories": {key: 0 for key in MOOD_CATEGORIES} | {"neutral": 3},
        "cause": "none",
        "updated_at": 0.0,
    }


def baseline_mood(traits, *, now=0.0, hour=None):
    """Ánimo base determinista a partir de los traits y la hora.

    Es el punto de reposo del ánimo y el respaldo cuando el modelo no declara
    uno. `hour` permite fijar la hora en tests; por defecto se deriva de `now`.
    """
    model = traits if isinstance(traits, dict) else {}
    expresiva = _clamp(model.get("expresiva", 3), 1, 5)
    timida = _clamp(model.get("timida", 3), 1, 5)
    juguetona = _clamp(model.get("juguetona", 3), 1, 5)
    celosa = _clamp(model.get("celosa", 3), 1, 5)
    sarcastica = _clamp(model.get("sarcastica", 3), 1, 5)
    curiosa = _clamp(model.get("curiosa", 3), 1, 5)

    if hour is None:
        try:
            hour = int((float(now) // 3600) % 24)
        except (TypeError, ValueError):
            hour = 12

    valence = round(
        ((expresiva - 3) + (juguetona - 3) - (celosa - 3) - (sarcastica - 3))
        / 2
    )
    energy = round((expresiva + juguetona + (6 - timida)) / 3)
    if hour < 6 or hour >= 23:
        energy -= 1
    warmth = round(
        (expresiva + curiosa + (6 - sarcastica) + (6 - celosa)) / 4
    )
    valence = _clamp(valence, MOOD_VALENCE_MIN, MOOD_VALENCE_MAX)
    energy = _clamp(energy, MOOD_AROUSAL_MIN, MOOD_AROUSAL_MAX)
    warmth = _clamp(warmth, MOOD_AROUSAL_MIN, MOOD_AROUSAL_MAX)
    return {
        "label": label_for_axes(valence, energy, warmth),
        "valence": valence,
        "energy": energy,
        "warmth": warmth,
        "categories": categories_from_axes(valence, energy, warmth),
        "cause": "none",
        "updated_at": 0.0,
    }


def _step_towards(current, target, max_step=MOOD_MAX_STEP):
    if target > current:
        return min(target, current + max_step)
    if target < current:
        return max(target, current - max_step)
    return current


def blend_mood(previous, proposed, *, now=0.0, baseline=None):
    """Suaviza el ánimo propuesto contra el anterior (inercia por eje).

    La etiqueta del propuesto manda (es la lectura cualitativa del modelo),
    pero los ejes solo se mueven como máximo `MOOD_MAX_STEP` por turno. Si el
    ánimo anterior lleva demasiado tiempo sin actualizarse, se parte de la
    base para que no arrastre un estado viejo.
    """
    target = normalize_mood(proposed) or normalize_mood(baseline) or default_mood()
    current = normalize_mood(previous)
    if current is None:
        target["updated_at"] = float(now)
        return target

    last = float(current.get("updated_at", 0.0) or 0.0)
    is_stale = bool(last) and (float(now) - last) > MOOD_STALE_SECONDS
    if is_stale:
        current = normalize_mood(baseline) or default_mood()

    return {
        "label": target["label"],
        "valence": _step_towards(
            current["valence"], target["valence"], MOOD_MAX_STEP
        ),
        "energy": _step_towards(
            current["energy"], target["energy"], MOOD_MAX_STEP
        ),
        "warmth": _step_towards(
            current["warmth"], target["warmth"], MOOD_MAX_STEP
        ),
        "categories": {
            key: _clamp(
                _step_towards(
                    current["categories"][key],
                    target["categories"][key],
                    MOOD_MAX_STEP,
                ),
                0,
                MOOD_CATEGORY_MAX,
            )
            for key in MOOD_CATEGORIES
        },
        "cause": target["cause"],
        "updated_at": float(now),
    }


def normalize_history(raw):
    """Normaliza `world["mood_history"]` (lista de snapshots) en el sitio."""
    if not isinstance(raw, list):
        return []
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        mood = normalize_mood(item)
        if mood is None:
            continue
        try:
            mood["ts"] = float(item.get("ts", 0.0) or 0.0)
        except (TypeError, ValueError):
            mood["ts"] = 0.0
        mood["user_id"] = str(item.get("user_id") or "")
        mood["channel_id"] = str(item.get("channel_id") or "")
        mood["source"] = (
            "model" if item.get("source") == "model" else "fallback"
        )
        entries.append(mood)
    return entries[-MOOD_HISTORY_MAX:]


def apply_mood(
    world,
    raw,
    *,
    now,
    user_id="",
    channel_id="",
    traits=None,
):
    """Actualiza el ánimo del mundo y registra el snapshot del turno.

    Devuelve `(mood, source)` donde `source` es `"model"` si el modelo declaró
    un ánimo usable o `"fallback"` si se usó la base determinista.
    """
    if not isinstance(world, dict):
        return None, "fallback"
    baseline = baseline_mood(traits, now=now)
    proposed = normalize_mood(raw)
    source = "model" if proposed is not None else "fallback"
    mood = blend_mood(
        world.get("mood"),
        proposed or baseline,
        now=now,
        baseline=baseline,
    )
    mood["user_id"] = str(user_id) if user_id is not None else ""
    world["mood"] = mood

    history = normalize_history(world.get("mood_history"))
    history.append(
        {
            **mood,
            "ts": float(now),
            "channel_id": str(channel_id) if channel_id is not None else "",
            "source": source,
        }
    )
    world["mood_history"] = history[-MOOD_HISTORY_MAX:]
    return mood, source


# ============================================================
# Render
# ============================================================


def _signed(value):
    return f"{value:+d}" if int(value) >= 0 else str(int(value))


def _mood_categories(mood):
    if not isinstance(mood, dict):
        return {key: 0 for key in MOOD_CATEGORIES}
    raw = mood.get("categories")
    if isinstance(raw, dict) and _has_categories(raw):
        return normalize_categories(raw)
    try:
        valence = _clamp(
            mood.get("valence", 0), MOOD_VALENCE_MIN, MOOD_VALENCE_MAX
        )
        energy = _clamp(
            mood.get("energy", 3), MOOD_AROUSAL_MIN, MOOD_AROUSAL_MAX
        )
        warmth = _clamp(
            mood.get("warmth", 3), MOOD_AROUSAL_MIN, MOOD_AROUSAL_MAX
        )
    except (TypeError, ValueError):
        valence, energy, warmth = 0, 3, 3
    return categories_from_axes(valence, energy, warmth)


def mood_ranked_categories(mood):
    """Categorías activas ordenadas por intensidad (y orden canónico)."""
    categories = _mood_categories(mood)
    ranked = [
        (key, categories[key])
        for key in MOOD_CATEGORIES
        if categories[key] >= 1
    ]
    ranked.sort(key=lambda item: (-item[1], MOOD_CATEGORIES.index(item[0])))
    return ranked


def mood_primary_category(mood):
    """Categoría dominante de un ánimo (o `neutral` si no hay ninguna)."""
    ranked = mood_ranked_categories(mood)
    return ranked[0][0] if ranked else "neutral"


def mood_visible_categories(
    mood,
    *,
    max_visible=None,
    min_secondary=None,
):
    """Categorías que se muestran: principal + secundaria si pesa lo bastante.

    La principal siempre aparece. La secundaria solo si alcanza
    `MOOD_CATEGORY_MIN_SECONDARY` y hay hueco hasta `MOOD_CATEGORY_MAX_VISIBLE`.
    """
    max_visible = MOOD_CATEGORY_MAX_VISIBLE if max_visible is None else max_visible
    min_secondary = (
        MOOD_CATEGORY_MIN_SECONDARY if min_secondary is None else min_secondary
    )
    ranked = mood_ranked_categories(mood)
    if not ranked:
        return [("neutral", 3)]
    visible = [ranked[0]]
    for item in ranked[1:]:
        if len(visible) >= max_visible:
            break
        if item[1] < min_secondary:
            continue
        visible.append(item)
    return visible


def mood_category_color(mood):
    """Color del embed según la categoría principal."""
    return MOOD_CATEGORY_COLORS[mood_primary_category(mood)]


def render_mood_bar(key, intensity, *, width=MOOD_BAR_WIDTH):
    """Barra de texto de una categoría, p. ej. `Entusiasmo  ████████░░ 4/5`."""
    value = _clamp(intensity, 0, MOOD_CATEGORY_MAX)
    filled = int(round(value / MOOD_CATEGORY_MAX * width))
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    name = mood_category_display(key)
    return f"{name:<10}  {bar} {value}/{MOOD_CATEGORY_MAX}"


def render_mood_meter(mood, *, previous=None):
    """Línea visible del ánimo: categorías con barra y cambio de principal."""
    parts = [
        render_mood_bar(key, intensity)
        for key, intensity in mood_visible_categories(mood)
    ]
    text = " · ".join(parts)
    if previous is not None:
        current_key = mood_primary_category(mood)
        previous_key = mood_primary_category(previous)
        if current_key != previous_key:
            text += f" (antes: {mood_category_display(previous_key)})"
    return text


def render_mood_sparkline(history, *, limit=12):
    """Secuencia de emojis con la categoría principal de cada turno."""
    entries = normalize_history(history)[-max(1, int(limit)):]
    return " ".join(
        MOOD_CATEGORY_EMOJI[mood_primary_category(entry)] for entry in entries
    )


def _attitude_line(mood, *, affinity_points, display_name):
    rank = level_rank(affinity_level(affinity_points)[0])
    if rank <= 3:
        base = "distante, con la guardia alta"
    elif rank <= 5:
        base = "cordial, sin excesiva confianza"
    elif rank <= 7:
        base = "cercana y cálida"
    else:
        base = "muy cercana y afectuosa"

    warmth = int(mood.get("warmth", 3) or 3)
    if warmth <= 2:
        base += ", más reservada de lo habitual"
    elif warmth >= 4:
        base += ", con más calidez de lo habitual"

    line = f"Con {display_name} tu actitud es {base}."
    if mood.get("label") in ("molesta", "melancolica") and rank >= 6:
        line += (
            f" Aunque estés así, no descargues el malestar en {display_name}."
        )
    return line


def render_mood_section(
    mood,
    *,
    traits=None,
    affinity_points=0,
    display_name="",
    now=0.0,
):
    """Sección de prompt con el ánimo del turno (y la actitud por persona)."""
    current = normalize_mood(mood) or baseline_mood(traits, now=now)
    categories_text = " · ".join(
        f"{mood_category_display(key)} {intensity}/5"
        for key, intensity in mood_visible_categories(current)
    )
    lines = [
        (
            f"Ahora mismo estás {current['label']}: valencia "
            f"{_signed(current['valence'])}/2, energía "
            f"{current['energy']}/5, cercanía {current['warmth']}/5."
        ),
        f"Categorías activas: {categories_text}.",
    ]
    if current.get("cause") and current["cause"] != "none":
        lines.append(f"Motivo: «{current['cause']}».")
    if display_name:
        lines.append(
            _attitude_line(
                current,
                affinity_points=affinity_points,
                display_name=display_name,
            )
        )
    lines.append(
        "Muéstralo con tono, ritmo y gestos; no anuncies tu ánimo ni lo "
        "expliques. El gif debe ser coherente con este ánimo. Si el ánimo "
        "choca con la afinidad, la afinidad manda en el trato hacia esta "
        "persona."
    )
    return "\n\n=== ÁNIMO DE ESTE TURNO ===\n" + "\n".join(lines)


def _format_time(ts):
    try:
        return time.strftime("%H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return "--:--"


def render_mood_history(world, *, include_cause=False, limit=10):
    """Línea temporal del ánimo para el comando `!animo-airi`."""
    world = world if isinstance(world, dict) else {}
    history = normalize_history(world.get("mood_history"))
    current = normalize_mood(world.get("mood"))
    if current is None and history:
        current = history[-1]
    if current is None:
        return (
            "Airi todavía no ha registrado ningún ánimo. "
            "Habla con ella un turno y vuelve a mirar."
        )

    lines = [
        f"**Ánimo actual:** {render_mood_meter(current)}"
    ]
    if current.get("cause") and current["cause"] != "none" and include_cause:
        lines.append(f"**Motivo:** {current['cause']}")
    recent = history[-max(1, int(limit)):]
    if recent:
        lines.append("**Últimos turnos:**")
        for entry in reversed(recent):
            row = (
                f"• {_format_time(entry.get('ts', 0.0))} — "
                f"{render_mood_meter(entry)}"
            )
            if include_cause and entry.get("cause") and entry["cause"] != "none":
                row += f" · motivo: {entry['cause']}"
            lines.append(row)
    sparkline = render_mood_sparkline(history)
    if sparkline:
        lines.append(f"**Evolución:** {sparkline}")
    return "\n".join(lines)


__all__ = [
    "MOOD_AXES_BY_LABEL",
    "MOOD_CATEGORIES",
    "MOOD_CATEGORY_COLORS",
    "MOOD_CATEGORY_EMOJI",
    "MOOD_CATEGORY_NAMES",
    "MOOD_LABELS",
    "MOOD_LABELS_ES",
    "MOOD_SCHEMA",
    "apply_mood",
    "baseline_mood",
    "blend_mood",
    "categories_from_axes",
    "default_mood",
    "label_for_axes",
    "mood_category_color",
    "mood_category_display",
    "mood_label_display",
    "mood_primary_category",
    "mood_ranked_categories",
    "mood_visible_categories",
    "normalize_categories",
    "normalize_history",
    "normalize_label",
    "normalize_mood",
    "render_mood_bar",
    "render_mood_history",
    "render_mood_meter",
    "render_mood_section",
    "render_mood_sparkline",
]
