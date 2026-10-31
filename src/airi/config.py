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
import warnings
from dataclasses import dataclass

from airi.domain.constants import ENV_FALSE_VALUES, ENV_TRUE_VALUES, env_int

DEFAULT_TRACE_KEEP_LAST = 500
DEFAULT_BACKUP_RETENTION = 5
DEFAULT_SEASON_RETENTION = 3
DEFAULT_PUBLISH_TTL_SECONDS = 900
DEFAULT_TURN_RETENTION_SECONDS = 7 * 24 * 3600
_WARNED_FLAGS: set[str] = set()


def _env_first(*names, default=""):
    """Primer valor de entorno no vacío entre `names`, o `default`."""
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip() != "":
            return value
    return default


def _env_flag_once(name: str, default: bool) -> bool:
    """Lee un flag y avisa una sola vez por clave ante valores inválidos."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ENV_TRUE_VALUES:
        return True
    if value in ENV_FALSE_VALUES:
        return False
    if name not in _WARNED_FLAGS:
        warnings.warn(
            f"{name}={raw!r} no es un booleano válido; se usa {default}.",
            UserWarning,
            stacklevel=2,
        )
        _WARNED_FLAGS.add(name)
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
    # Retención de copias y archivos de temporada.
    backup_retention: int = DEFAULT_BACKUP_RETENTION
    season_retention: int = DEFAULT_SEASON_RETENTION
    # Vigencia de una respuesta confirmada pendiente de publicar.
    publish_ttl_seconds: int = DEFAULT_PUBLISH_TTL_SECONDS
    # Tiempo que se conserva un registro de turno ya resuelto.
    turn_retention_seconds: int = DEFAULT_TURN_RETENTION_SECONDS
    # Percepción temporal del prompt y zona IANA opcional (vacío = zona del sistema).
    time_context: bool = True
    timezone: str = ""
    # Verificación semántica breve del borrador antes de publicarlo.
    conversation_review: bool = True
    # Habilita la herramienta de búsqueda web (la decisión sigue siendo del
    # modelo; esto solo permite apagarla por completo).
    web_search: bool = True

    @property
    def state_path(self) -> str:
        return os.path.join(self.data_dir, "state.json")

    @property
    def lock_path(self) -> str:
        return os.path.join(self.data_dir, ".airi.lock")

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
            backup_retention=env_int(
                "AIRI_BACKUP_RETENTION", DEFAULT_BACKUP_RETENTION
            ),
            season_retention=env_int(
                "AIRI_SEASON_RETENTION", DEFAULT_SEASON_RETENTION
            ),
            publish_ttl_seconds=env_int(
                "AIRI_PUBLISH_TTL_SECONDS", DEFAULT_PUBLISH_TTL_SECONDS
            ),
            turn_retention_seconds=env_int(
                "AIRI_TURN_RETENTION_SECONDS", DEFAULT_TURN_RETENTION_SECONDS
            ),
            time_context=_env_flag_once("AIRI_TIME_CONTEXT", True),
            timezone=_env_first("AIRI_TIMEZONE", default=""),
            conversation_review=_env_flag_once("AIRI_CONVERSATION_REVIEW", True),
            web_search=_env_flag_once("AIRI_WEB_SEARCH", True),
        )
