"""Retención acotada de temporadas archivadas y copias de migración."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from airi.config import (
    DEFAULT_BACKUP_RETENTION,
    DEFAULT_SEASON_RETENTION,
)

log = logging.getLogger(__name__)

BACKUP_PREFIX = "pre-aggregate-"


@dataclass
class RetentionReport:
    removed_seasons: list[str] = field(default_factory=list)
    removed_backups: list[str] = field(default_factory=list)
    kept_seasons: int = 0
    kept_backups: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def removed_total(self) -> int:
        return len(self.removed_seasons) + len(self.removed_backups)


class RetentionService:
    """Elimina solo lo que queda fuera de los límites configurados."""

    def __init__(
        self,
        data_dir: str | os.PathLike[str],
        *,
        season_limit: int | None = None,
        backup_limit: int | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.season_limit = max(
            0,
            int(
                DEFAULT_SEASON_RETENTION
                if season_limit is None
                else season_limit
            ),
        )
        self.backup_limit = max(
            0,
            int(
                DEFAULT_BACKUP_RETENTION
                if backup_limit is None
                else backup_limit
            ),
        )

    def prune(self) -> RetentionReport:
        report = RetentionReport()
        self._prune_seasons(report)
        self._prune_backups(report)
        return report

    # ------------------------------------------------------------------
    # Temporadas
    # ------------------------------------------------------------------

    def _prune_seasons(self, report: RetentionReport) -> None:
        root = self.data_dir / "archive" / "seasons"
        if not root.is_dir():
            return
        seasons = sorted(
            (path for path in root.iterdir() if path.is_dir() and path.name.isdigit()),
            key=lambda path: int(path.name),
        )
        keep = seasons[-self.season_limit :] if self.season_limit else []
        keep_names = {path.name for path in keep}
        report.kept_seasons = len(keep)
        for path in seasons:
            if path.name in keep_names:
                continue
            try:
                shutil.rmtree(path)
                report.removed_seasons.append(path.name)
            except OSError as exc:
                report.errors.append(f"temporada {path.name}: {exc}")
                log.warning("No se pudo borrar la temporada %s: %s", path.name, exc)

    # ------------------------------------------------------------------
    # Copias
    # ------------------------------------------------------------------

    def _prune_backups(self, report: RetentionReport) -> None:
        root = self.data_dir / "backups"
        if not root.is_dir():
            return
        backups = sorted(
            (
                path
                for path in root.iterdir()
                if path.is_dir() and path.name.startswith(BACKUP_PREFIX)
            ),
            key=lambda path: (path.stat().st_mtime, path.name),
        )
        keep = backups[-self.backup_limit :] if self.backup_limit else []
        keep_names = {path.name for path in keep}
        report.kept_backups = len(keep)
        for path in backups:
            if path.name in keep_names:
                continue
            try:
                shutil.rmtree(path)
                report.removed_backups.append(path.name)
            except OSError as exc:
                report.errors.append(f"copia {path.name}: {exc}")
                log.warning("No se pudo borrar la copia %s: %s", path.name, exc)
