"""Puerto: búsqueda web.

La búsqueda devuelve notas estructuradas (título + extracto), nunca un texto
formateado con URLs o ranking. El servicio que las consume decide cómo
presentarlas al modelo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class WebResult:
    """Un resultado individual de búsqueda."""

    title: str
    snippet: str


@dataclass(frozen=True, slots=True)
class WebSearchNotes:
    """Resultados de una búsqueda. Vacío = la búsqueda no encontró nada."""

    results: tuple[WebResult, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not any(
            (result.title or "").strip() or (result.snippet or "").strip()
            for result in self.results
        )


class WebSearchClient(Protocol):
    """Búsqueda web que devuelve notas o ``None`` si la API falla."""

    async def search(self, query: str) -> WebSearchNotes | None:
        ...
