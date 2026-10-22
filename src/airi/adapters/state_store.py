"""Almacén atómico del estado canónico (tareas 2.1 y 2.2).

Protocolo de escritura:

1. se valida el agregado antes de tocar el sistema de archivos;
2. se escribe y sincroniza un archivo temporal;
3. si el activo es válido, se rota una copia exacta a ``state.json.bak``;
4. se reemplaza el activo de forma atómica;
5. se sincroniza el directorio (mejor esfuerzo).

La recuperación nunca sustituye un archivo inválido por valores por defecto:
lo copia a cuarentena y, si hay una copia válida, restaura desde ella. Si no
hay ninguna copia válida, el estado queda bloqueado.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

from airi.adapters.fs_utils import fsync_dir
from airi.domain.state_schema import validate_state
from airi.ports.state_store import LoadResult, LoadStatus, SaveResult

ACTIVE_NAME = "state.json"
BACKUP_NAME = "state.json.bak"
TEMP_NAME = "state.json.tmp"
BACKUP_TEMP_NAME = "state.json.bak.tmp"


class StateStoreError(RuntimeError):
    """Error base del almacén de estado."""


class StateValidationError(StateStoreError, ValueError):
    """El agregado no cumple el esquema y no se ha tocado el disco."""


class AtomicWriteError(StateStoreError):
    """La escritura falló y el estado activo anterior sigue intacto."""


class StateStore:
    """Persistencia atómica de ``state.json`` con copia y cuarentena."""

    def __init__(self, root: str | os.PathLike[str], quarantine_root=None):
        self.root = Path(root)
        self.quarantine_root = (
            Path(quarantine_root)
            if quarantine_root is not None
            else self.root / "quarantine"
        )

    # ------------------------------------------------------------------
    # Rutas
    # ------------------------------------------------------------------

    @property
    def active_path(self) -> Path:
        return self.root / ACTIVE_NAME

    @property
    def backup_path(self) -> Path:
        return self.root / BACKUP_NAME

    @property
    def temp_path(self) -> Path:
        return self.root / TEMP_NAME

    @property
    def backup_temp_path(self) -> Path:
        return self.root / BACKUP_TEMP_NAME

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------

    def load(self) -> LoadResult:
        active = self._read(self.active_path)
        if active[0] is LoadStatus.OK:
            self._remove_temp()
            return LoadResult(LoadStatus.OK, data=active[1])

        if active[0] is LoadStatus.MISSING:
            backup = self._read(self.backup_path)
            if backup[0] is LoadStatus.OK:
                self._restore(backup[1])
                return LoadResult(
                    LoadStatus.OK,
                    data=backup[1],
                    recovered=True,
                    error="activo ausente; restaurado desde la copia",
                )
            if backup[0] is LoadStatus.MISSING:
                self._remove_temp()
                return LoadResult(LoadStatus.MISSING)
            return LoadResult(
                LoadStatus.BLOCKED,
                error=f"activo ausente y copia inválida: {backup[2]}",
            )

        # Activo inválido: conservar copia exacta antes de intentar recuperar.
        try:
            quarantine = self.quarantine(self.active_path)
        except OSError as exc:
            return LoadResult(
                LoadStatus.BLOCKED,
                error=f"no se pudo poner el activo en cuarentena: {exc}",
            )

        backup = self._read(self.backup_path)
        if backup[0] is LoadStatus.OK:
            try:
                self._restore(backup[1])
            except OSError as exc:
                return LoadResult(
                    LoadStatus.BLOCKED,
                    quarantine_path=quarantine,
                    error=f"no se pudo restaurar la copia: {exc}",
                )
            return LoadResult(
                LoadStatus.OK,
                data=backup[1],
                recovered=True,
                quarantine_path=quarantine,
                error="activo inválido; restaurado desde la copia",
            )

        if backup[0] is LoadStatus.INVALID:
            try:
                self.quarantine(self.backup_path)
            except OSError:
                pass

        return LoadResult(
            LoadStatus.BLOCKED,
            quarantine_path=quarantine,
            error=f"activo y copia inválidos: {active[2]} / {backup[2]}",
        )

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------

    def save(self, aggregate: Mapping[str, object]) -> SaveResult:
        validation = validate_state(aggregate)
        if not validation.ok:
            raise StateValidationError("; ".join(validation.errors))

        self.root.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            aggregate, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")

        try:
            self._write_temp(self.temp_path, encoded)
            if self.active_path.exists():
                status, _, _ = self._read(self.active_path)
                if status is LoadStatus.OK:
                    self._write_temp(self.backup_temp_path, self.active_path.read_bytes())
                    os.replace(self.backup_temp_path, self.backup_path)
                    self._set_mode(self.backup_path)
                    fsync_dir(self.root)
                else:
                    # El activo ilegible no se usa como copia, pero se conserva.
                    try:
                        self.quarantine(self.active_path)
                    except OSError:
                        pass

            os.replace(self.temp_path, self.active_path)
        except OSError as exc:
            raise AtomicWriteError(
                f"no se pudo guardar el estado en {self.active_path}: {exc}"
            ) from exc

        self._set_mode(self.active_path)
        fsync_dir(self.root)
        return SaveResult(
            ok=True,
            path=str(self.active_path),
            state_version=int(aggregate.get("state_version", 0) or 0),
        )

    def quarantine(self, path: str | os.PathLike[str]) -> str:
        """Copia un archivo inválido a cuarentena y devuelve su ruta."""
        source = Path(path)
        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        stamp = time.time_ns()
        target = self.quarantine_root / f"{stamp}-{source.name}"
        suffix = 1
        while target.exists():
            target = self.quarantine_root / f"{stamp}-{suffix}-{source.name}"
            suffix += 1
        target.write_bytes(source.read_bytes())
        self._set_mode(target)
        return str(target)

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _read(self, path: Path):
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return LoadStatus.MISSING, None, "archivo ausente"
        except OSError as exc:
            return LoadStatus.BLOCKED, None, str(exc)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return LoadStatus.INVALID, None, f"json inválido: {exc}"
        validation = validate_state(data)
        if not validation.ok:
            return LoadStatus.INVALID, None, "; ".join(validation.errors)
        return LoadStatus.OK, data, ""

    def _restore(self, data: Mapping[str, Any]) -> None:
        encoded = json.dumps(
            data, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_temp(self.temp_path, encoded)
        os.replace(self.temp_path, self.active_path)
        self._set_mode(self.active_path)
        fsync_dir(self.root)

    def _write_temp(self, path: Path, data: bytes) -> None:
        with open(path, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        self._set_mode(path)

    def _set_mode(self, path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _remove_temp(self) -> None:
        try:
            self.temp_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
