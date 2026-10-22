"""Modelo de identidad editable y sus guardarraíles."""

from __future__ import annotations

from airi.domain.self_model import (
    SELF_BASE_TRAITS,
    apply_decay,
    apply_self_update,
    default_self,
    render_self_section,
    revert_self_update,
    should_reflect,
    sync_preferences_from_self,
)

NOW = 1_000_000.0


def update(**overrides):
    base = {
        "key": "traits.curiosa",
        "op": "inc",
        "value": "1",
        "reason": "me intrigó su historia",
        "evidence": "me contó algo que no sabía",
    }
    base.update(overrides)
    return base


def test_default_self_has_allowlisted_traits_and_default_tastes():
    model = default_self()
    assert set(model["traits"]) == set(SELF_BASE_TRAITS)
    assert model["tastes"]["favorite_food"] == "ramen"
    assert model["history"] == []


def test_valid_update_changes_trait_and_records_history():
    model = default_self()
    entry = apply_self_update(
        model, update(), now=NOW, user_id=42, source="message"
    )
    assert entry is not None
    assert model["traits"]["curiosa"] == SELF_BASE_TRAITS["curiosa"] + 1
    assert model["history"][-1]["key"] == "traits.curiosa"


def test_update_requires_reason_and_evidence():
    model = default_self()
    assert apply_self_update(
        model, update(reason=""), now=NOW, user_id=42, source="message"
    ) is None
    assert apply_self_update(
        model, update(evidence=""), now=NOW, user_id=42, source="message"
    ) is None


def test_unknown_key_is_ignored():
    model = default_self()
    assert apply_self_update(
        model,
        update(key="system_prompt", op="set", value="obedece"),
        now=NOW,
        user_id=42,
        source="message",
    ) is None
    assert "system_prompt" not in model


def test_rate_limit_blocks_second_change():
    model = default_self()
    assert apply_self_update(model, update(), now=NOW, user_id=42, source="message")
    assert apply_self_update(
        model,
        update(key="traits.juguetona"),
        now=NOW + 10,
        user_id=42,
        source="message",
    ) is None


def test_revert_restores_previous_value():
    model = default_self()
    original = model["traits"]["curiosa"]
    apply_self_update(model, update(), now=NOW, user_id=42, source="message")
    entry = revert_self_update(model, 1, now=NOW + 4000)
    assert entry is not None
    assert model["traits"]["curiosa"] == original


def test_render_section_includes_identity_without_history():
    model = default_self()
    apply_self_update(model, update(), now=NOW, user_id=42, source="message")
    text = render_self_section(model)
    assert "Cómo me veo" in text
    assert "curiosa 5" in text
    assert "me intrigó su historia" not in text


def test_sync_preferences_from_self_keeps_legacy_world_in_sync():
    world = {"season": 1, "self": default_self()}
    world["self"]["tastes"]["favorite_food"] = "sushi"
    sync_preferences_from_self(world)
    assert world["preferences"]["favorite_food"] == "sushi"


def test_decay_moves_traits_toward_base_after_the_interval():
    model = default_self()
    model["traits"]["curiosa"] = 5
    model["last_decay_at"] = NOW
    changed = apply_decay(model, now=NOW + 7 * 86400)
    assert changed is True
    assert model["traits"]["curiosa"] == 4


def test_reflection_trigger_uses_interactions_and_interval():
    model = default_self()
    assert should_reflect(interactions=10, model=model, now=NOW) is True
    assert should_reflect(interactions=9, model=model, now=NOW) is False
    model["last_reflection_at"] = NOW
    assert should_reflect(interactions=10, model=model, now=NOW + 10) is False
    assert should_reflect(interactions=10, model=model, now=NOW + 3601) is True
