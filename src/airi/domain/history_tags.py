"""Vista de inferencia del historial: identidad y afinidad por interlocutor.

Módulo PURO (sin `AppState`, Discord ni HTTP). Transforma el historial canónico
—mensajes limpios, tal y como se persisten— en la lista de mensajes que se envía
al LLM, anteponiendo a cada intervención de usuario una etiqueta determinista:

    [speaker=KOKODA|affinity=-16|level=Molesta] Airi que fácil eres
    [speaker=Nuevo|affinity=unknown] hola

Principios (ver plan maestro, secciones 2 y 5):

- **La etiqueta se reconstruye, nunca se persiste.** El historial canónico se
  mantiene limpio; la vista se genera en cada inferencia con la afinidad vigente.
- **Identidad estructurada como fuente de verdad.** `author_id` manda sobre el
  nombre visible. Los historiales antiguos se resuelven por prefijo de nombre y
  un índice inverso de usuarios, sin elegir al azar cuando hay homónimos.
- **Afinidad ausente ≠ afinidad cero.** Un usuario sin registro se marca como
  `affinity=unknown` (neutral), distinto de un registro real de cero puntos.
- **Resistencia a etiquetas falsificadas.** Como la etiqueta se genera desde
  metadatos internos, una cadena que el usuario escriba con la misma forma no se
  confunde con una etiqueta de Airi, y NUNCA se borra contenido del usuario.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable

from airi.domain.time_perception import format_clock, local_day_label

#: Etiqueta que genera este módulo (para detectar una vista ya etiquetada).
_TAG_RE = re.compile(r"^\[speaker=[^\]]*\]\s*")
_TEMPORAL_VIEW_RE = re.compile(
    r"^\[(?:ahora|hace \d+ (?:min|h|día(?:s)?)"
    r"|(?:hoy|ayer|\d{2}/\d{2}) \d{2}:\d{2})\]\s+\[speaker=[^\]]*\]"
)
#: Caracteres que romperían el formato de la etiqueta.
_UNSAFE_NAME_RE = re.compile(r"[\[\]|=\r\n\t]+")
_WS_RE = re.compile(r"\s+")

#: Valor de afinidad cuando el usuario no tiene registro.
UNKNOWN_AFFINITY = "unknown"


def normalize_name(name) -> str:
    """Normaliza un nombre para búsquedas (case-insensitive, espacios). No es identidad."""
    if not isinstance(name, str):
        return ""
    return _WS_RE.sub(" ", name.strip()).casefold()


def build_user_index(users) -> dict:
    """Índice inverso ``nombre_normalizado -> (user_id, ...)``.

    Nunca sobrescribe: los homónimos se acumulan en una tupla para que el
    llamador pueda detectar la colisión en lugar de atribuir a una persona al
    azar.
    """
    index: dict[str, list[str]] = {}
    if not isinstance(users, Mapping):
        return {}
    for uid, entry in users.items():
        name = entry.get("name") if isinstance(entry, Mapping) else None
        normalized = normalize_name(name)
        if not normalized:
            continue
        index.setdefault(normalized, []).append(str(uid))
    return {key: tuple(ids) for key, ids in index.items()}


def build_display_names(users) -> tuple[str, ...]:
    """Nombres visibles únicos, los más largos primero (para casar prefijos)."""
    seen: dict[str, str] = {}
    if isinstance(users, Mapping):
        for entry in users.values():
            name = entry.get("name") if isinstance(entry, Mapping) else None
            if isinstance(name, str) and name.strip():
                seen.setdefault(name.strip(), name.strip())
    return tuple(sorted(seen, key=len, reverse=True))


def safe_name(name) -> str:
    """Sanea un nombre para que no rompa el formato de la etiqueta."""
    if not isinstance(name, str):
        name = "" if name is None else str(name)
    cleaned = _UNSAFE_NAME_RE.sub(" ", name)
    return _WS_RE.sub(" ", cleaned).strip()


@dataclass(frozen=True)
class AffinityInfo:
    """Afinidad de un interlocutor. `points is None` ⇒ sin registro (neutral)."""

    points: int | None = None
    level: str | None = None

    @property
    def registered(self) -> bool:
        return self.points is not None


#: `resolver(user_id | None, name | None) -> AffinityInfo | None`.
Resolver = Callable[[object, object], "AffinityInfo | None"]


def format_identity_tag(name, affinity) -> str:
    """Etiqueta corta y determinista a partir de un nombre y una afinidad."""
    display = safe_name(name) or "?"
    if affinity is None or getattr(affinity, "points", None) is None:
        return f"[speaker={display}|affinity={UNKNOWN_AFFINITY}]"
    level = safe_name(getattr(affinity, "level", None)) or "?"
    return f"[speaker={display}|affinity={int(affinity.points)}|level={level}]"


def time_tag(ts, now, zone=None) -> str:
    """Etiqueta temporal de una intervención; vacío si falta un instante válido.

    Los huecos recientes se expresan en minutos; a partir de una hora se usa el
    día local real (``hoy``/``ayer``/``DD/MM``) más la hora, para que el modelo
    no tenga que calcular la fecha a partir de un ``hace N h`` ambiguo.
    """
    try:
        stamp = float(ts)
        reference = float(now)
    except (TypeError, ValueError, OverflowError):
        return ""
    if not math.isfinite(stamp) or not math.isfinite(reference):
        return ""
    if stamp > reference:
        return "[ahora]"
    seconds = reference - stamp
    if seconds < 60:
        return "[ahora]"
    if seconds < 3600:
        return f"[hace {max(1, int(seconds // 60))} min]"
    return f"[{local_day_label(reference, stamp, zone)} {format_clock(stamp, zone)}]"


def _resolve_name(name, index) -> str | None:
    """user_id si (y solo si) el nombre normalizado identifica a UNA persona."""
    ids = index.get(normalize_name(name)) if index else None
    if ids and len(ids) == 1:
        return ids[0]
    return None


def _strip_prefix(content, name) -> str:
    """Quita el prefijo ``"<nombre>: "`` generado por el servicio, si lo hay."""
    if not name:
        return content
    for prefix in (f"{name}: ", f"{name}:"):
        if content.startswith(prefix):
            return content[len(prefix):].lstrip()
    return content


def _split_legacy_prefix(content, names) -> tuple[str | None, str]:
    """Recupera (nombre, texto) de un mensaje antiguo ``"Nombre: texto"``.

    Solo reconoce un prefijo si empieza por un nombre conocido (el generado por
    el propio servicio). No parte ciegamente por el primer `": "`, de modo que
    los nombres con dos puntos, el texto del usuario y los homónimos se tratan
    sin corromper la identidad.
    """
    for name in names:
        if content.startswith(f"{name}: "):
            return name, content[len(name) + 2:].lstrip()
    return None, content


def _author_of(msg, index, names) -> tuple[str | None, str | None, str]:
    """Devuelve ``(user_id, nombre, texto)`` de una intervención de usuario."""
    content = msg.get("content")
    if not isinstance(content, str):
        content = ""
    author_id = msg.get("author_id")
    author_name = msg.get("author_name")
    name = author_name if isinstance(author_name, str) and author_name.strip() else None

    if author_id is not None:
        # Identidad estructurada: fuente de verdad. El nombre visible solo se usa
        # para mostrar y para quitar el prefijo redundante del contenido.
        return str(author_id), name, _strip_prefix(content, name)
    if name is not None:
        return _resolve_name(name, index), name, _strip_prefix(content, name)
    # Historial antiguo sin metadatos: prefijo de nombre + índice inverso.
    legacy_name, text = _split_legacy_prefix(content, names)
    uid = _resolve_name(legacy_name, index) if legacy_name else None
    return uid, legacy_name, text


def build_inference_history(
    history, resolver: Resolver, *, users=None, now=None, zone=None
) -> list:
    """Construye la vista enviada al LLM a partir del historial canónico.

    - No muta `history` ni sus diccionarios; devuelve mensajes nuevos.
    - Conserva el orden y el contenido; solo antepone la etiqueta de identidad a
      los turnos de usuario y la de destinatario a los del asistente.
    - Los mensajes de salida solo llevan `role` + `content`: los metadatos
      internos (`author_id`, `author_name`, `reply_to_user_id`...) nunca se
      filtran a la API.
    - Es determinista e idempotente: una vista ya etiquetada no se re-etiqueta ni
      duplica la etiqueta.
    """
    index = build_user_index(users)
    names = build_display_names(users)
    view: list = []

    for msg in history or []:
        if not isinstance(msg, Mapping):
            # Estructura no admitida: se omite de forma determinista. Nunca se
            # accede a `.get()` sobre algo que no sea un mensaje.
            continue
        role = msg.get("role")
        content = msg.get("content")
        if not isinstance(content, str):
            continue

        if role == "user":
            # Idempotencia: una vista previa ya etiquetada se conserva tal cual.
            if msg.get("author_id") is None and (
                _TAG_RE.match(content) or _TEMPORAL_VIEW_RE.match(content)
            ):
                view.append({"role": "user", "content": content})
                continue
            user_id, name, text = _author_of(msg, index, names)
            affinity = resolver(user_id, name)
            tag = format_identity_tag(name, affinity)
            temporal = time_tag(msg.get("ts"), now, zone) if now is not None else ""
            prefix = f"{temporal} " if temporal else ""
            view.append({"role": "user", "content": f"{prefix}{tag} {text}".rstrip()})
            continue

        # Asistente (o cualquier rol no-usuario): se conserva el contenido y,
        # si consta, se anota a quién iba dirigida la respuesta.
        reply_name = msg.get("reply_to_user_name")
        if isinstance(reply_name, str) and reply_name.strip():
            content = f"[reply_to={safe_name(reply_name)}] {content}"
        view.append({"role": "assistant", "content": content})

    return view
