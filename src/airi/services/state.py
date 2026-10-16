"""Estado compartido de la aplicación (inyectable, sin globales)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from airi.domain.affinity import (
    AFFINITY_DELTA_MAX,
    apply_affinity_delta,
    default_entry,
)
from airi.domain.affinity import (
    entry_points as _entry_points,
)
from airi.domain.diary import add_diary_entry, new_diary_entry
from airi.domain.memories import user_memories as _user_memories
from airi.domain.self_model import (
    add_discovery,
    apply_decay,
    apply_self_update,
    mark_reflection,
    migrate_from_world,
    normalize_self,
    should_reflect,
)
from airi.observability.trace_store import TraceStore


def _noop(*args, **kwargs):
    return None


def _default_trace_store() -> TraceStore:
    """TraceStore en memoria (sin disco) para no romper tests/existentes."""
    return TraceStore(None)


@dataclass
class AppState:
    """Agrupa todos los estados mutables + callbacks de persistencia.

    Los callbacks se pasan como callables para que la capa externa (bot.py)
    pueda resolverlos en tiempo de llamada (p. ej. tras monkeypatch en tests).
    """

    affinity: dict = field(default_factory=dict)
    world: dict = field(default_factory=dict)
    dates: dict = field(default_factory=dict)
    memories: dict = field(default_factory=dict)
    diary: list = field(default_factory=list)
    users: dict = field(default_factory=dict)
    histories: dict = field(default_factory=dict)

    save_affinity: Callable[[], None] = _noop
    save_world: Callable[[], None] = _noop
    save_dates: Callable[[], None] = _noop
    save_memories: Callable[[], None] = _noop
    save_diary: Callable[[], None] = _noop
    save_users: Callable[[], None] = _noop
    # Hook opcional para aplicar afinidad vía la fachada externa (bot.py),
    # de modo que se mantengan sus logs y sea monkeypatchable en tests.
    apply_affinity_fn: Callable[..., int] | None = None
    # Almacén de eventos de turno (ring buffer + disco opcional).
    traces: TraceStore = field(default_factory=_default_trace_store)

    # ------------------------------------------------------------------
    # Afinidad
    # ------------------------------------------------------------------

    def affinity_entry(self, user_id) -> dict:
        key = str(user_id)
        entry = self.affinity.get(key)
        if not isinstance(entry, dict):
            entry = default_entry()
            self.affinity[key] = entry
        else:
            for fname, default in default_entry().items():
                entry.setdefault(fname, default)
        return entry

    def entry_points(self, user_id) -> int:
        return _entry_points(self.affinity.get(str(user_id)))

    def apply_affinity(
        self,
        user_id,
        delta,
        *,
        now,
        delta_max=AFFINITY_DELTA_MAX,
        delta_min=None,
    ) -> int:
        """Aplica el cambio juzgado por Airi y persiste. Devuelve el aplicado."""
        if self.apply_affinity_fn is not None:
            kwargs = {"delta_max": delta_max}
            if delta_min is not None:
                kwargs["delta_min"] = delta_min
            applied = self.apply_affinity_fn(user_id, delta, now=now, **kwargs)
            return int(applied or 0)
        entry = self.affinity_entry(user_id)
        if delta_min is None:
            applied = apply_affinity_delta(entry, delta, now, delta_max=delta_max)
        else:
            applied = apply_affinity_delta(
                entry, delta, now, delta_max=delta_max, delta_min=delta_min
            )
        self.save_affinity()
        return applied

    # ------------------------------------------------------------------
    # Identidad ("self")
    # ------------------------------------------------------------------

    def self_model(self) -> dict:
        """Devuelve `world["self"]`, sembrándolo/migrándolo si hace falta.

        La identidad vive dentro de `world` para reutilizar `save_world` y los
        snapshots de replay. La primera vez absorbe los gustos antiguos de
        `world["preferences"]` (`migrate_from_world`).
        """
        if not isinstance(self.world, dict):
            self.world = {}
        model = self.world.get("self")
        if not isinstance(model, dict):
            model = migrate_from_world(self.world)
            self.world["self"] = model
            self.save_world()
        return normalize_self(model)

    def apply_self_change(self, update, *, now, user_id, source="message"):
        """Aplica UN cambio de identidad juzgado por Airi y persiste el mundo.

        Devuelve la entrada del historial o None si el cambio fue rechazado.
        """
        model = self.self_model()
        entry = apply_self_update(
            model, update, now=now, user_id=user_id, source=source
        )
        if entry is not None:
            self.save_world()
        return entry

    def add_self_discovery(self, text, *, now, source="reflection"):
        """Añade un autodescubrimiento y persiste. Devuelve la entrada o None."""
        model = self.self_model()
        entry = add_discovery(model, text, now=now, source=source)
        if entry is not None:
            self.save_world()
        return entry

    def mark_self_reflection(self, *, now) -> None:
        """Sella el reloj de reflexión (aunque no produzca cambios)."""
        model = self.self_model()
        mark_reflection(model, now)
        self.save_world()

    def should_reflect_self(self, *, interactions, now, force=False) -> bool:
        """True si toca una reflexión introspectiva ahora."""
        return should_reflect(
            interactions=interactions,
            model=self.self_model(),
            now=now,
            force=force,
        )

    def decay_self(self, *, now) -> bool:
        """Aplica la deriva lenta hacia la base. Devuelve si cambió algo."""
        model = self.self_model()
        before = model.get("last_decay_at")
        changed = apply_decay(model, now)
        if changed or model.get("last_decay_at") != before:
            self.save_world()
        return changed

    # ------------------------------------------------------------------
    # Diario
    # ------------------------------------------------------------------

    def log_diary_event(self, kind, user, text, *, now=None) -> bool:
        """Añade una entrada al diario y la persiste. Devuelve si se guardó.

        `user` puede ser un id plano o un objeto con `.id`; el nombre se
        resuelve en tiempo de llamada (tras `register_activity`).
        """
        if not text:
            return False
        if now is None:
            import time as _time

            now = _time.time()
        uid = getattr(user, "id", user)
        entry = new_diary_entry(
            kind,
            uid,
            self.display_name(uid),
            text,
            now,
            season=int((self.world or {}).get("season", 1) or 1),
        )
        if add_diary_entry(self.diary, entry):
            self.save_diary()
            return True
        return False

    # ------------------------------------------------------------------
    # Memorias
    # ------------------------------------------------------------------

    def user_memories(self, user_id) -> list:
        return _user_memories(self.memories, user_id)

    def display_name(self, user_id) -> str:
        entry = self.users.get(str(user_id))
        if isinstance(entry, dict) and entry.get("name"):
            return str(entry["name"])
        return "alguien"
