"""Capacidades activas en un turno (eventos que aplican).

En arquitectura hexagonal, el contexto del turno declara qué eventos están
activos (cita, búsqueda web, regalo, etc.). El prompt y el schema se construyen
a partir de estas capacidades, sin acoplar la lógica a booleanos sueltos.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TurnCapabilities:
    date_active: bool = False
    web_enabled: bool = False
    # Extensible: añadir nuevos flags aquí sin tocar la lógica de selección.
    extra: dict = field(default_factory=dict)

    def has(self, name: str) -> bool:
        if name == "date":
            return self.date_active
        if name == "web":
            return self.web_enabled
        return bool(self.extra.get(name, False))
