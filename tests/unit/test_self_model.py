"""Modelo de identidad editable y sus guardarraíles."""

from __future__ import annotations

from airi.domain.self_model import (
    SELF_BASE_TRAITS,
    apply_decay,
    apply_self_update,
    default_self,
    normalize_self,
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
    assert model["tastes"]["favorite_food"] == "postres y dulces"
    assert {"videojuegos", "lol"} <= set(model["tastes"]["loves"])
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


def test_configured_daily_limit_allows_two_changes_then_blocks_until_window_expires(
    monkeypatch,
):
    import airi.domain.self_model as self_model

    monkeypatch.setattr(self_model, "SELF_KEY_DAILY_LIMIT", 2)
    monkeypatch.setattr(self_model, "SELF_KEY_DAILY_SECONDS", 100)
    monkeypatch.setattr(self_model, "SELF_UPDATE_MIN_INTERVAL", 0)
    model = default_self()

    assert apply_self_update(
        model, update(op="set", value="5"), now=NOW, user_id=42, source="message"
    )
    assert apply_self_update(
        model, update(op="set", value="4"), now=NOW + 10, user_id=42,
        source="message",
    )
    assert apply_self_update(
        model, update(op="set", value="5"), now=NOW + 20, user_id=42,
        source="message",
    ) is None

    assert apply_self_update(
        model, update(op="set", value="5"), now=NOW + 111, user_id=42,
        source="message",
    )


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


# ---------------------------------------------------------------------------
# Baseline desde el env (`SELF_BASE_TRAITS`) + aprendizaje como desviación
# ---------------------------------------------------------------------------


def _patch_baseline(monkeypatch, base):
    """Fija el baseline vigente y la lista de rasgos del módulo."""
    import airi.domain.self_model as self_model

    monkeypatch.setattr(
        self_model, "SELF_TRAITS_ALLOWLIST", tuple(base.keys())
    )
    monkeypatch.setattr(
        self_model, "SELF_BASE_TRAITS", {k: int(v) for k, v in base.items()}
    )


def test_default_self_stamps_baseline_and_empty_learning(monkeypatch):
    _patch_baseline(monkeypatch, {"curiosa": 2})
    model = default_self()
    assert model["traits"] == {"curiosa": 2}
    assert model["traits_learned"] == {}
    assert model["traits_base"] == {"curiosa": 2}
    assert model["traits"]["curiosa"] == 2  # el env manda en identidad nueva


def test_legacy_identity_without_baseline_obeys_env_baseline(monkeypatch):
    """Identidad legada idéntica al baseline del código: el env manda al inicio."""

    _patch_baseline(monkeypatch, {"curiosa": 2})
    legacy = {
        "version": 1,
        "traits": {"curiosa": 4},  # == LEGACY_self baseline del código
        "history": [],
    }
    normalize_self(legacy)
    assert legacy["traits_learned"] == {}
    assert legacy["traits"]["curiosa"] == 2


def test_baseline_change_preserves_learned_character_then_decays(monkeypatch):
    """Si Airi aprendió, cambiar el env no borra lo aprendido al reiniciar."""

    OLD = {"curiosa": 4}
    NEW = {"curiosa": 2}
    _patch_baseline(monkeypatch, OLD)
    model = {
        "version": 1,
        "traits": {"curiosa": 3},  # aprendió a ser menos curiosa (−1)
        "traits_base": dict(OLD),
        "history": [],
    }
    normalize_self(model)
    # El personaje se preserva: 3 = base nueva (2) + aprendizaje (−1)…
    assert model["traits_learned"] == {"curiosa": -1}
    assert model["traits"]["curiosa"] == 3
    # …y el decaimiento la lleva de vuelta al nuevo baseline del env.
    _patch_baseline(monkeypatch, NEW)
    model["last_decay_at"] = NOW
    changed = apply_decay(model, now=NOW + 7 * 86400)
    assert changed is True
    assert model["traits_learned"] == {"curiosa": 0}
    assert model["traits"]["curiosa"] == 2


def test_manual_absolute_edit_is_backfilled_as_learning(monkeypatch):
    """Editar a mano el valor absoluto no lo borra el próximo normalize."""

    _patch_baseline(monkeypatch, {"curiosa": 2})
    model = {
        "version": 1,
        "traits": {"curiosa": 4},
        "traits_learned": {},
        "traits_base": {"curiosa": 2},
        "history": [],
    }
    normalize_self(model)
    assert model["traits_learned"] == {"curiosa": 2}
    assert model["traits"]["curiosa"] == 4


def test_self_update_records_learning_relative_to_baseline(monkeypatch):
    _patch_baseline(monkeypatch, {"curiosa": 2})
    model = default_self()
    entry = apply_self_update(
        model, update(), now=NOW, user_id=42, source="message"
    )
    assert entry is not None
    assert model["traits"]["curiosa"] == 3
    assert model["traits_learned"] == {"curiosa": 1}
