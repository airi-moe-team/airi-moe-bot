"""Migración explícita e idempotente de los JSON heredados."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from airi.domain.state_schema import (
    CURRENT_SCHEMA_VERSION,
    LEGACY_DATASETS,
    OPTIONAL_LEGACY_DATASETS,
    validate_legacy_dataset,
    validate_state,
)
from airi.ports.state_store import LoadStatus, StateStorePort

log = logging.getLogger(__name__)

LEGACY_FILES = tuple(f"{name}.json" for name in LEGACY_DATASETS)
OPTIONAL_LEGACY_FILES = tuple(f"{name}.json" for name in OPTIONAL_LEGACY_DATASETS)
MANIFEST_NAME = "migration.json"
BACKUPS_DIR = "backups"
QUARANTINE_DIR = "quarantine"


class MigrationStatus(str, Enum):
    MIGRATED = "migrated"
    ALREADY_MIGRATED = "already_migrated"
    NO_SOURCE = "no_source"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class MigrationPlan:
    source_files: dict[str, Path] = field(default_factory=dict)
    source_hash: str = ""
    missing: tuple[str, ...] = ()
    corrupt: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.source_files) and not self.missing and not self.corrupt


@dataclass(frozen=True)
class MigrationResult:
    status: MigrationStatus
    source_hash: str = ""
    backup_dir: str = ""
    quarantine_dir: str = ""
    message: str = ""


class LegacyMigrator:
    """Convierte los seis JSON heredados en el agregado canónico una vez."""

    def __init__(self, data_dir: str | os.PathLike[str], store: StateStorePort):
        self.data_dir = Path(data_dir)
        self.store = store

    def plan(self) -> MigrationPlan:
        files: dict[str, Path] = {}
        missing: list[str] = []
        corrupt: list[str] = []
        for name in LEGACY_FILES:
            path = self.data_dir / name
            if not path.exists():
                missing.append(name)
                continue
            files[name] = path
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                corrupt.append(name)
                continue
            validation = validate_legacy_dataset(name.removesuffix(".json"), data)
            if not validation.ok:
                corrupt.append(name)
        for name in OPTIONAL_LEGACY_FILES:
            path = self.data_dir / name
            if not path.exists():
                continue
            files[name] = path
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                corrupt.append(name)
                continue
            validation = validate_legacy_dataset(name.removesuffix(".json"), data)
            if not validation.ok:
                corrupt.append(name)
        return MigrationPlan(
            source_files=files,
            source_hash=source_hash_of(files),
            missing=tuple(missing),
            corrupt=tuple(corrupt),
        )

    def run(self) -> MigrationResult:
        existing = self.store.load()
        if existing.status is LoadStatus.OK:
            plan = self.plan()
            return MigrationResult(
                MigrationStatus.ALREADY_MIGRATED,
                source_hash=plan.source_hash,
                message="el estado canónico ya existe",
            )
        if existing.status is LoadStatus.BLOCKED:
            return MigrationResult(
                MigrationStatus.BLOCKED,
                quarantine_dir=existing.quarantine_path,
                message=existing.error or "estado canónico bloqueado",
            )

        plan = self.plan()
        if not plan.source_files:
            return MigrationResult(
                MigrationStatus.NO_SOURCE, message="no hay datos heredados"
            )
        if plan.missing or plan.corrupt:
            quarantine = self._quarantine_corrupt(plan)
            detail = []
            if plan.missing:
                detail.append("faltan: " + ", ".join(plan.missing))
            if plan.corrupt:
                detail.append("ilegibles: " + ", ".join(plan.corrupt))
            return MigrationResult(
                MigrationStatus.BLOCKED,
                source_hash=plan.source_hash,
                quarantine_dir=quarantine,
                message="; ".join(detail),
            )

        try:
            backup = self._backup(plan)
            aggregate = self._build_aggregate(plan)
        except (OSError, json.JSONDecodeError) as exc:
            return MigrationResult(
                MigrationStatus.BLOCKED,
                source_hash=plan.source_hash,
                message=f"no se pudo preparar la migración: {exc}",
            )
        validation = validate_state(aggregate)
        if not validation.ok:
            return MigrationResult(
                MigrationStatus.BLOCKED,
                source_hash=plan.source_hash,
                backup_dir=str(backup),
                message="; ".join(validation.errors),
            )
        try:
            result = self.store.save(aggregate)
        except Exception as exc:
            return MigrationResult(
                MigrationStatus.BLOCKED,
                source_hash=plan.source_hash,
                backup_dir=str(backup),
                message=f"no se pudo activar el estado migrado: {exc}",
            )
        if not result.ok:
            return MigrationResult(
                MigrationStatus.BLOCKED,
                source_hash=plan.source_hash,
                backup_dir=str(backup),
                message=result.error or "escritura de migración fallida",
            )

        try:
            self._write_manifest(plan, backup)
        except OSError as exc:
            log.warning("No se pudo escribir el manifiesto de migración: %s", exc)
        return MigrationResult(
            MigrationStatus.MIGRATED,
            source_hash=plan.source_hash,
            backup_dir=str(backup),
            message="migración completada",
        )

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _backup(self, plan: MigrationPlan) -> Path:
        root = self.data_dir / BACKUPS_DIR
        root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime())
        target = root / f"pre-aggregate-{stamp}"
        suffix = 1
        while target.exists():
            target = root / f"pre-aggregate-{stamp}-{suffix}"
            suffix += 1
        target.mkdir(parents=True)
        for name, path in plan.source_files.items():
            destination = target / name
            shutil.copy2(path, destination)
            _set_private_mode(destination)
            if destination.read_bytes() != path.read_bytes():
                raise OSError(f"copia de migración no verificable: {name}")
        return target

    def _build_aggregate(self, plan: MigrationPlan) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "state_version": 0,
            "histories": {},
            "turn_records": {},
            "message_index": {},
            "archive": {},
        }
        for name, path in plan.source_files.items():
            key = name.removesuffix(".json")
            data[key] = json.loads(path.read_text(encoding="utf-8"))
        for name in LEGACY_FILES:
            key = name.removesuffix(".json")
            data.setdefault(key, [] if key == "diary" else {})
        return data

    def _quarantine_corrupt(self, plan: MigrationPlan) -> str:
        paths = []
        for name in plan.corrupt:
            path = self.data_dir / name
            if path.exists():
                try:
                    paths.append(self.store.quarantine(path))
                except OSError as exc:
                    log.warning("No se pudo poner %s en cuarentena: %s", name, exc)
        if not paths:
            return ""
        parent = Path(paths[0]).parent
        return str(parent)

    def _write_manifest(self, plan: MigrationPlan, backup: Path) -> None:
        payload = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "source_hash": plan.source_hash,
            "migrated_at": time.time(),
            "backup_dir": str(backup),
            "source_files": sorted(plan.source_files),
        }
        path = self.data_dir / MANIFEST_NAME
        temp = path.with_suffix(".json.tmp")
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        _set_private_mode(temp)
        os.replace(temp, path)


def source_hash_of(files: dict[str, Path]) -> str:
    """Huella estable de los archivos de origen."""
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(files[name].read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()


def _set_private_mode(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
