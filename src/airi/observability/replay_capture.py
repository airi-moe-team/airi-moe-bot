"""Validación y adaptador offline para capturas de búsqueda de replay."""

from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from airi.ports.web_search import WebResult, WebSearchNotes

CAPTURE_SCHEMA = "airi.web-capture.v1"
MAX_CAPTURE_BYTES = 1_000_000
MAX_CAPTURE_RESULTS = 10
MAX_CAPTURE_TEXT = 12_000
VALID_STATUSES = {"not_requested", "empty", "results", "error"}


@dataclass(frozen=True)
class WebCapture:
    correlation_id: str
    status: str
    query: str | None
    results: tuple[WebResult, ...]


def normalize_query(query: str) -> str:
    """Normalización conservadora: Unicode NFC y espacios colapsados."""
    return " ".join(unicodedata.normalize("NFC", query).split())


def _validate_capture(data, expected_correlation_id: str) -> WebCapture:
    if not isinstance(data, dict) or data.get("schema") != CAPTURE_SCHEMA:
        raise ValueError("captura inválida: schema no compatible")
    if data.get("correlation_id") != expected_correlation_id:
        raise ValueError("captura inválida: correlation_id no coincide")
    status = data.get("status")
    if status not in VALID_STATUSES:
        raise ValueError("captura inválida: estado desconocido")
    query = data.get("query")
    if query is not None and (not isinstance(query, str) or len(query) > MAX_CAPTURE_TEXT):
        raise ValueError("captura inválida: consulta no válida")
    raw_results = data.get("results")
    if not isinstance(raw_results, list) or len(raw_results) > MAX_CAPTURE_RESULTS:
        raise ValueError("captura inválida: resultados no válidos")
    results = []
    for item in raw_results:
        if (not isinstance(item, dict) or set(item) - {"title", "snippet"}
                or not isinstance(item.get("title"), str)
                or not isinstance(item.get("snippet"), str)
                or len(item["title"]) > MAX_CAPTURE_TEXT
                or len(item["snippet"]) > MAX_CAPTURE_TEXT):
            raise ValueError("captura inválida: resultado no válido")
        results.append(WebResult(item["title"], item["snippet"]))
    if status == "empty" and results:
        raise ValueError("captura inválida: estado empty con resultados")
    if status == "results" and not results:
        raise ValueError("captura inválida: estado results sin resultados")
    if status in {"empty", "results"} and not query:
        raise ValueError("captura inválida: falta consulta")
    return WebCapture(expected_correlation_id, status, query, tuple(results))


def load_web_capture(path, *, correlation_id: str) -> WebCapture:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_CAPTURE_BYTES:
            raise ValueError("captura inválida: excede el tamaño máximo")
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"no se pudo leer captura local: {path}") from exc
    return _validate_capture(data, correlation_id)


def write_web_capture(path, *, correlation_id, status, query=None, results=(), replace=False):
    """Escribe un sidecar versionado atómico, restringido a permisos del usuario."""
    data = {
        "schema": CAPTURE_SCHEMA,
        "correlation_id": correlation_id,
        "status": status,
        "query": query,
        "results": [
            {
                "title": result["title"] if isinstance(result, dict) else result.title,
                "snippet": result["snippet"] if isinstance(result, dict) else result.snippet,
            }
            for result in results
        ],
    }
    _validate_capture(data, correlation_id)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not replace:
        raise FileExistsError(f"el artefacto de captura ya existe: {destination}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        if destination.exists() and not replace:
            raise FileExistsError(f"el artefacto de captura ya existe: {destination}")
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return str(destination)


class CapturedWebSearchClient:
    """Cliente offline: solo sirve evidencia para la consulta capturada."""

    def __init__(self, capture: WebCapture):
        self.capture = capture
        self.status = "capture_missing"

    async def search(self, query: str) -> WebSearchNotes | None:
        if self.capture.status == "error":
            self.status = "captured_error"
            return None
        if self.capture.status == "not_requested" or self.capture.query is None:
            self.status = "capture_missing"
            return None
        if normalize_query(query) != normalize_query(self.capture.query):
            self.status = "capture_mismatch"
            return None
        if self.capture.status == "empty":
            self.status = "captured_empty"
            return WebSearchNotes(())
        self.status = "captured_results"
        return WebSearchNotes(self.capture.results)
