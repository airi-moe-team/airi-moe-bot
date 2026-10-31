"""Herramienta de búsqueda web y presentación de sus notas.

La decisión de buscar es del modelo: esta capa solo define el contrato de la
herramienta, valida lo que devuelve y convierte los resultados en un bloque de
contexto para la generación final. No impone frases de respuesta.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from airi.ports.web_search import WebSearchNotes

log = logging.getLogger(__name__)

SEARCH_TOOL_NAME = "buscar_web"
QUERY_MAX_CHARS = 300
MOTIVO_MAX_CHARS = 300
NOTES_MAX_SNIPPET_CHARS = 600
NOTES_MAX_TITLE_CHARS = 200

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": SEARCH_TOOL_NAME,
        "description": (
            "Comprueba un dato concreto en internet. Úsala solo cuando "
            "necesites información actual o verificable que no esté en la "
            "conversación."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Consulta breve, objetiva y con las entidades del contexto.",
                },
                "motivo": {
                    "type": "string",
                    "description": "Motivo corto en primera persona para haber buscado.",
                },
            },
            "required": ["query", "motivo"],
            "additionalProperties": False,
        },
    },
}

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Petición de búsqueda generada por el modelo."""

    query: str
    motivo: str = ""


def _clean(value, limit):
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _arguments(raw):
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("Argumentos de tool call no son JSON válido: %r", raw[:200])
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


def parse_search_request(tool_calls) -> SearchRequest | None:
    """Extrae la primera llamada válida a ``buscar_web``.

    Acepta tanto la forma normalizada por el adaptador
    (``{"name", "arguments"}``) como la forma cruda de OpenAI
    (``{"function": {"name", "arguments"}}``).
    """
    for call in tool_calls or ():
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = function.get("name") or call.get("name")
        if name != SEARCH_TOOL_NAME:
            continue
        args = _arguments(function.get("arguments", call.get("arguments")))
        query = _clean(args.get("query"), QUERY_MAX_CHARS)
        if not query:
            continue
        return SearchRequest(
            query=query,
            motivo=_clean(args.get("motivo"), MOTIVO_MAX_CHARS),
        )
    return None


def note_years(notes: WebSearchNotes | None) -> tuple[str, ...]:
    """Años mencionados en las notas, sin interpretarlos como un hecho.

    Es un metadato para que el modelo pueda detectar versiones dispares; no
    afirma que haya contradicción ni redacta la respuesta.
    """
    if notes is None:
        return ()
    text = " ".join(
        f"{result.title} {result.snippet}" for result in notes.results
    )
    return tuple(sorted(set(_YEAR.findall(text))))


def _render_results(notes: WebSearchNotes) -> list[str]:
    lines = []
    for result in notes.results:
        title = _clean(result.title, NOTES_MAX_TITLE_CHARS)
        title = _URL.sub("", title).strip()
        snippet = _clean(result.snippet, NOTES_MAX_SNIPPET_CHARS)
        snippet = _URL.sub("", snippet).strip()
        if not title and not snippet:
            continue
        if title and snippet:
            lines.append(f"- {title}: {snippet}")
        else:
            lines.append(f"- {title or snippet}")
    return lines


def render_search_block(
    request: SearchRequest,
    notes: WebSearchNotes | None,
    *,
    failed: bool = False,
) -> str:
    """Bloque de contexto para la generación final.

    ``failed`` describe un hecho (no se encontró nada), no una frase que Airi
    deba repetir. Las reglas describen comportamiento; no incluyen respuestas
    de ejemplo para evitar que el modelo las parafrasee.
    """
    if failed or notes is None or notes.is_empty:
        return (
            "\n\n=== BÚSQUEDA EN LA WEB ===\n"
            "La búsqueda se ejecutó, pero no devolvió notas útiles. No digas "
            "que careces de acceso a internet ni que no buscaste. No inventes "
            "datos; reconoce el resultado vacío con tus propias palabras y "
            "sigue la conversación.\n"
        )

    lines = ["\n\n=== LO QUE ACABAS DE VER ==="]
    if request.motivo:
        lines.append(f"Has buscado porque {request.motivo}.")
    else:
        lines.append("Has buscado para comprobar un dato.")
    lines.append("Notas:")
    lines.extend(_render_results(notes))
    years = note_years(notes)
    if len(years) >= 2:
        lines.append(
            "Años mencionados en las notas: " + ", ".join(years) + "."
        )
    lines.extend(
        [
            "=== CÓMO CONTARLO ===",
            "- Integra la búsqueda como algo que acabas de hacer; no anuncies "
            "una consulta.",
            "- Da el dato y reacciona con tu opinión.",
            "- No inventes datos concretos que no estén en las notas.",
            "- Si las notas no coinciden, dilo y muestra tu duda.",
            '- Nada de URLs, listas de fuentes ni "según las fuentes".',
        ]
    )
    return "\n".join(lines) + "\n"
