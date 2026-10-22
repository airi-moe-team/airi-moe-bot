"""Puerto del almacén de estado (sin I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol


class LoadStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    INVALID = "invalid"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class LoadResult:
    status: LoadStatus
    data: Mapping[str, object] | None = None
    recovered: bool = False
    quarantine_path: str = ""
    error: str = ""


@dataclass(frozen=True)
class SaveResult:
    ok: bool
    path: str = ""
    state_version: int = 0
    error: str = ""


class StateStorePort(Protocol):
    """Contrato mínimo que consume la capa de persistencia."""

    def load(self) -> LoadResult: ...

    def save(self, aggregate: Mapping[str, object]) -> SaveResult: ...
