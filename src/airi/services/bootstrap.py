"""Arranque del estado: cargar, migrar o inicializar sin sobrescribir."""

from __future__ import annotations

from dataclasses import dataclass

from airi.domain.affinity import default_world
from airi.ports.state_store import LoadResult, LoadStatus, StateStorePort
from airi.services.migration import LegacyMigrator, MigrationResult, MigrationStatus
from airi.services.persistence import StatePersistence
from airi.services.state import AppState


class BootstrapError(RuntimeError):
    """El estado no se puede cargar de forma segura."""

    def __init__(self, message: str, *, quarantine_path: str = ""):
        super().__init__(message)
        self.quarantine_path = quarantine_path


@dataclass(frozen=True)
class BootstrapResult:
    state: AppState
    persistence: StatePersistence
    load: LoadResult
    migration: MigrationResult | None
    recovered: bool


def bootstrap_state(
    *,
    store: StateStorePort,
    migrator: LegacyMigrator,
) -> BootstrapResult:
    """Construye un `AppState` cargado o inicializado de forma segura."""
    state = AppState(
        world=default_world(),
        affinity={},
        dates={},
        memories={},
        diary=[],
        users={},
        histories={},
    )
    persistence = StatePersistence(store)
    persistence.bind(state)

    result = persistence.load()
    migration: MigrationResult | None = None

    if result.status is LoadStatus.MISSING:
        migration = migrator.run()
        if migration.status in (
            MigrationStatus.MIGRATED,
            MigrationStatus.ALREADY_MIGRATED,
        ):
            result = persistence.load()
        elif migration.status is MigrationStatus.BLOCKED:
            raise BootstrapError(
                migration.message or "migración bloqueada",
                quarantine_path=migration.quarantine_dir,
            )
        else:
            # NO_SOURCE: instalación nueva; no hay migración que reportar.
            migration = None

    if result.status in (LoadStatus.BLOCKED, LoadStatus.INVALID):
        raise BootstrapError(
            result.error or "estado inválido",
            quarantine_path=result.quarantine_path,
        )

    return BootstrapResult(
        state=state,
        persistence=persistence,
        load=result,
        migration=migration,
        recovered=result.recovered,
    )
