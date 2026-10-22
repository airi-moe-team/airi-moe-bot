"""Fachada transaccional entre el estado en memoria y el almacén atómico."""

from __future__ import annotations

import copy
import logging
from contextlib import contextmanager
from enum import Enum
from typing import Iterator

from airi.domain.relationships import normalize_world
from airi.domain.state_schema import CURRENT_SCHEMA_VERSION, validate_state
from airi.ports.state_store import LoadResult, StateStorePort
from airi.services.state import AppState

log = logging.getLogger(__name__)

_SAVE_CALLBACKS = (
    "save_world",
    "save_affinity",
    "save_dates",
    "save_memories",
    "save_diary",
    "save_users",
    "save_state",
)

_SNAPSHOT_FIELDS = (
    "world",
    "affinity",
    "dates",
    "memories",
    "diary",
    "users",
    "histories",
    "turn_records",
    "message_index",
    "archive",
    "state_version",
)


class SaveKind(str, Enum):
    """Tipo de commit: cambia o no la versión de dominio."""

    DOMAIN = "domain"
    METADATA = "metadata"


class PersistenceError(RuntimeError):
    """No se pudo confirmar el estado; la instantánea anterior sigue vigente."""


class StatePersistence:
    """Conecta `AppState` con el almacén y agrupa mutaciones relacionadas."""

    def __init__(self, store: StateStorePort):
        self.store = store
        self.state: AppState | None = None
        self._in_transaction = False
        self._dirty = False
        self._kinds: set[SaveKind] = set()

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------

    def bind(self, state: AppState) -> None:
        """Conecta el estado y sustituye sus callbacks por los del servicio."""
        self.state = state
        for name in _SAVE_CALLBACKS:
            setattr(state, name, self.request_save)

    def load(self) -> LoadResult:
        """Carga el agregado en el estado conectado, si es válido."""
        state = self._require_state()
        result = self.store.load()
        if result.data is not None:
            self._apply(state, result.data)
        return result

    # ------------------------------------------------------------------
    # Guardado
    # ------------------------------------------------------------------

    def request_save(self) -> None:
        """Callback que usan las mutaciones de `AppState`."""
        if self._in_transaction:
            self._dirty = True
            self._kinds.add(SaveKind.DOMAIN)
            return
        self.save()

    def save(self, *, kind: SaveKind = SaveKind.DOMAIN) -> None:
        """Persiste el estado completo, o lo marca si hay una transacción."""
        self._require_state()
        if self._in_transaction:
            self._dirty = True
            self._kinds.add(kind)
            return
        self._save_now(kind)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Agrupa mutaciones y persiste una sola vez al salir con éxito.

        La transacción debe usarse dentro del bloqueo de commit de la
        aplicación y no puede contener `await`.
        """
        if self._in_transaction:
            raise PersistenceError("no se permite anidar transacciones")
        snapshot = self._snapshot()
        self._in_transaction = True
        self._dirty = False
        self._kinds = set()
        try:
            yield
        except BaseException:
            self._restore(snapshot)
            self._reset_transaction()
            raise
        else:
            try:
                if self._dirty:
                    kind = (
                        SaveKind.DOMAIN
                        if SaveKind.DOMAIN in self._kinds
                        else SaveKind.METADATA
                    )
                    self._save_now(kind)
            except BaseException:
                self._restore(snapshot)
                raise
            finally:
                self._reset_transaction()

    # ------------------------------------------------------------------
    # Agregado
    # ------------------------------------------------------------------

    def aggregate(self) -> dict:
        """Representación persistible del estado en memoria."""
        state = self._require_state()
        return {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "state_version": int(state.state_version),
            "world": state.world,
            "affinity": state.affinity,
            "dates": state.dates,
            "memories": state.memories,
            "diary": state.diary,
            "users": state.users,
            "histories": state.histories,
            "turn_records": state.turn_records,
            "message_index": state.message_index,
            "archive": state.archive,
        }

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _save_now(self, kind: SaveKind) -> None:
        state = self._require_state()
        previous = int(state.state_version)
        if kind is SaveKind.DOMAIN:
            state.state_version = previous + 1
        try:
            aggregate = self.aggregate()
            validation = validate_state(aggregate)
            if not validation.ok:
                raise PersistenceError(
                    "estado inválido: " + "; ".join(validation.errors)
                )
            result = self.store.save(aggregate)
        except PersistenceError:
            state.state_version = previous
            raise
        except Exception as exc:
            state.state_version = previous
            raise PersistenceError(f"no se pudo guardar el estado: {exc}") from exc
        if not result.ok:
            state.state_version = previous
            raise PersistenceError(result.error or "escritura de estado fallida")
        if kind is SaveKind.DOMAIN:
            log.debug("estado confirmado en versión %s", state.state_version)

    def _apply(self, state: AppState, data) -> None:
        state.world = copy.deepcopy(data.get("world") or {})
        # Migración en carga: registros antiguos sin `relationships` arrancan en
        # etapa neutra y la pareja oficial existente se conserva sin inventar
        # motivos históricos.
        normalize_world(state.world)
        state.affinity = copy.deepcopy(data.get("affinity") or {})
        state.dates = copy.deepcopy(data.get("dates") or {})
        state.memories = copy.deepcopy(data.get("memories") or {})
        state.diary = copy.deepcopy(data.get("diary") or [])
        state.users = copy.deepcopy(data.get("users") or {})
        state.histories = {
            _history_key(key): copy.deepcopy(value)
            for key, value in (data.get("histories") or {}).items()
        }
        state.turn_records = copy.deepcopy(data.get("turn_records") or {})
        state.message_index = copy.deepcopy(data.get("message_index") or {})
        state.archive = copy.deepcopy(data.get("archive") or {})
        state.state_version = int(data.get("state_version", 0) or 0)

    def _snapshot(self) -> dict:
        state = self._require_state()
        return {name: copy.deepcopy(getattr(state, name)) for name in _SNAPSHOT_FIELDS}

    def _restore(self, snapshot: dict) -> None:
        state = self._require_state()
        for name, value in snapshot.items():
            setattr(state, name, value)

    def _reset_transaction(self) -> None:
        self._in_transaction = False
        self._dirty = False
        self._kinds = set()

    def _require_state(self) -> AppState:
        if self.state is None:
            raise PersistenceError("la persistencia no está conectada a un estado")
        return self.state


def _history_key(key):
    """Los ids de canal se guardan como texto en JSON; se recuperan como int."""
    try:
        return int(key)
    except (TypeError, ValueError):
        return key
