"""Estado en memoria para tests (reemplaza a los repos JSON)."""

from __future__ import annotations

from airi.domain.affinity import default_world
from airi.domain.diary import add_diary_entry, new_diary_entry
from airi.services.state import AppState


class InMemoryRepository:
    """Implementa `airi.ports.repository.Repository` en memoria."""

    def __init__(self, data=None):
        self.data = {} if data is None else data
        self.saves = 0

    def load(self):
        return self.data

    def save(self, data):
        self.data = data
        self.saves += 1


def make_state(*, now=1_000_000.0, **overrides):
    """Crea un AppState limpio con contadores de guardado y diario capturado.

    Devuelve `(state, counters)`. `counters` tiene claves: affinity, world,
    dates, memories, diary, users (nº de guardados) y `diary_logs`
    (lista de `(kind, user_id, text)`).
    """
    counters = {"affinity": 0, "world": 0, "dates": 0, "memories": 0,
                "diary": 0, "users": 0, "diary_logs": []}

    def _count(key):
        def _fn():
            counters[key] += 1
        return _fn

    state = AppState(
        affinity=overrides.get("affinity", {}),
        world=overrides.get("world") or default_world(),
        dates=overrides.get("dates", {}),
        memories=overrides.get("memories", {}),
        diary=overrides.get("diary", []),
        users=overrides.get("users", {}),
        histories=overrides.get("histories", {}),
        save_affinity=_count("affinity"),
        save_world=_count("world"),
        save_dates=_count("dates"),
        save_memories=_count("memories"),
        save_diary=_count("diary"),
        save_users=_count("users"),
    )

    default_now = now

    def log_diary_event(kind, user, text, *, now=None):
        if not text:
            return False
        uid = getattr(user, "id", user)
        name = getattr(user, "display_name", None) or str(user)
        counters["diary_logs"].append((kind, str(uid), text))
        entry = new_diary_entry(
            kind, uid, name, text, default_now if now is None else now,
            season=int(state.world.get("season", 1) or 1),
        )
        return add_diary_entry(state.diary, entry)

    state.log_diary_event = log_diary_event
    return state, counters
