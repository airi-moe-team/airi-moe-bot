"""Tests de la identidad de Airi en `AppState` (siembra, cambios y deriva)."""

from airi.domain.affinity import default_preferences
from airi.domain.self_model import default_self
from airi.services.state import AppState

NOW = 1_000_000.0


def _state(**overrides):
    saved = []
    state = AppState(
        world=overrides.pop("world", {"season": 1}),
        save_world=lambda: saved.append(True),
        **overrides,
    )
    return state, saved


def test_self_model_seeds_from_preferences_and_persists():
    world = {"season": 1, "preferences": default_preferences()}
    state, saved = _state(world=world)

    model = state.self_model()

    assert model is state.world["self"]
    assert model["traits"]["curiosa"] >= 1
    assert model["tastes"]["favorite_flower"]
    assert saved == [True]


def test_self_model_existing_is_normalized_without_reseeding():
    world = {"season": 1, "self": {"self_concept": "soy Airi"}}
    state, saved = _state(world=world)

    model = state.self_model()

    assert model["self_concept"] == "soy Airi"
    assert set(model["traits"])  # normalizado con rasgos de la allowlist
    assert saved == []  # no había que sembrar


def test_apply_self_change_persists_and_returns_entry():
    state, saved = _state(world={"season": 1, "self": default_self()})

    entry = state.apply_self_change(
        {"key": "traits.curiosa", "op": "inc", "value": "1",
         "reason": "me intrigó", "evidence": "me contó algo nuevo"},
        now=NOW,
        user_id=7,
        source="message",
    )

    assert entry is not None
    assert state.world["self"]["traits"]["curiosa"] == entry["to"]
    assert saved == [True]


def test_apply_self_change_rejects_without_reason_and_does_not_persist():
    state, saved = _state(world={"season": 1, "self": default_self()})

    entry = state.apply_self_change(
        {"key": "traits.curiosa", "op": "inc", "value": "1",
         "reason": "none", "evidence": "none"},
        now=NOW,
        user_id=7,
    )

    assert entry is None
    assert saved == []


def test_add_self_discovery_persists():
    state, saved = _state(world={"season": 1, "self": default_self()})

    entry = state.add_self_discovery("me gustan los días de lluvia", now=NOW)

    assert entry is not None
    assert state.world["self"]["discoveries"][-1]["text"] == "me gustan los días de lluvia"
    assert saved == [True]


def test_decay_self_sets_clock_first_time_without_change():
    state, saved = _state(world={"season": 1, "self": default_self()})

    assert state.decay_self(now=NOW) is False
    assert state.world["self"]["last_decay_at"] == NOW
    assert saved == [True]


def test_mark_self_reflection_persists_clock():
    state, saved = _state(world={"season": 1, "self": default_self()})

    state.mark_self_reflection(now=NOW)

    assert state.world["self"]["last_reflection_at"] == NOW
    assert saved == [True]


def test_should_reflect_self_uses_interaction_counter():
    state, _ = _state()
    state.world["self"] = default_self()
    state.world["self"]["last_reflection_at"] = 0.0

    assert state.should_reflect_self(interactions=1, now=NOW) is False
    assert state.should_reflect_self(
        interactions=10, now=NOW, force=True
    ) is True
