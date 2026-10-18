"""Configuración de la aplicación leída del entorno (stdlib, sin dependencias).

Se usa un `dataclass` estándar en lugar de `pydantic-settings` porque en este
entorno no hay red para instalar dependencias nuevas. Los valores se leen una
vez con `Settings.from_env()`, reutilizando el patrón `env_int` del dominio.

Precedencia de nombres: se prefiere el prefijo `AIRI_` y se acepta el nombre
histórico sin prefijo (`AIRI_TRACE_DIR` → `TRACE_DIR`), igual que hace la CLI
`python -m airi.trace`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from airi.domain.constants import PENDING_MAX_AGE_SECONDS, env_flag, env_int

DEFAULT_TRACE_KEEP_LAST = 500


def _env_first(*names, default=""):
    """Primer valor de entorno no vacío entre `names`, o `default`."""
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip() != "":
            return value
    return default


@dataclass(frozen=True)
class Settings:
    """Ajustes de la aplicación."""

    # Directorio de datos (JSON de persistencia).
    data_dir: str = "data"
    # Directorio de trazas en disco (vacío = solo ring en memoria).
    trace_dir: str = ""
    # Tamaño del ring buffer en memoria (eventos inspeccionables con !debug).
    trace_keep_last: int = DEFAULT_TRACE_KEEP_LAST
    # Avisos de estado: anuncia en los canales autorizados que Airi se conecta
    # y se desconecta (embeds de sistema).
    online_notice: bool = True
    # Al arrancar, Airi contesta el último mensaje que quedó sin respuesta.
    answer_pending_on_start: bool = True
    # Antigüedad máxima (segundos) de ese mensaje pendiente.
    pending_max_age: int = PENDING_MAX_AGE_SECONDS

    @classmethod
    def from_env(cls) -> "Settings":
        """Construye los ajustes desde el entorno (una vez, al arrancar)."""
        return cls(
            data_dir=_env_first("AIRI_DATA_DIR", "DATA_DIR", default="data"),
            trace_dir=_env_first("AIRI_TRACE_DIR", "TRACE_DIR", default=""),
            trace_keep_last=env_int(
                "AIRI_TRACE_KEEP_LAST",
                env_int("TRACE_KEEP_LAST", DEFAULT_TRACE_KEEP_LAST),
            ),
            online_notice=env_flag("AIRI_ONLINE_NOTICE", True),
            answer_pending_on_start=env_flag("AIRI_ANSWER_PENDING_ON_START", True),
            pending_max_age=env_int("AIRI_PENDING_MAX_AGE", PENDING_MAX_AGE_SECONDS),
        )
