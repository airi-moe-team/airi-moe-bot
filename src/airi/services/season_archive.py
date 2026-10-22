"""Archivo validado de una temporada antes de reiniciarla."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Mapping

from airi.adapters.state_store import StateStore
from airi.domain.state_schema import validate_state


class SeasonArchiveError(RuntimeError):
    """No se pudo crear o validar el archivo de temporada."""


class SeasonArchiver:
    """Guarda una instantánea completa de la temporada en curso."""

    def __init__(self, data_dir: str | os.PathLike[str], *, clock=time.time):
        self.data_dir = Path(data_dir)
        self.clock = clock

    def archive(
        self, *, season: int, aggregate: Mapping[str, object]
    ) -> str:
        validation = validate_state(aggregate)
        if not validation.ok:
            raise SeasonArchiveError("; ".join(validation.errors))
        target = self.data_dir / "archive" / "seasons" / str(int(season))
        try:
            target.mkdir(parents=True, exist_ok=True)
            store = StateStore(target)
            result = store.save(aggregate)
            if not result.ok:
                raise SeasonArchiveError(
                    result.error or "no se pudo guardar el archivo de temporada"
                )
            meta = {
                "season": int(season),
                "archived_at": float(self.clock()),
                "schema_version": int(aggregate.get("schema_version", 0) or 0),
                "state_version": int(aggregate.get("state_version", 0) or 0),
            }
            self._write_meta(target / "meta.json", meta)
        except SeasonArchiveError:
            raise
        except Exception as exc:
            raise SeasonArchiveError(
                f"no se pudo archivar la temporada {season}: {exc}"
            ) from exc
        return str(target)

    @staticmethod
    def _write_meta(path: Path, payload: Mapping[str, object]) -> None:
        temp = path.with_suffix(".json.tmp")
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, path)
