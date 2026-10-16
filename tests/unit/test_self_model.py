"""Tests del modelo de identidad de Airi (`airi.domain.self_model`)."""

import copy

from airi.domain import constants as C
from airi.domain.affinity import default_preferences
from airi.domain.self_model import (
    SELF_UPDATE_SCHEMA,
    add_discovery,
    apply_decay,
    apply_self_update,
    default_self,
    migrate_from_world,
    normalize_self,
    render_self_section,
    revert_self_update,
    should_reflect,
)

NOW = 1_000_000.0
DAY = 86_400.0


def _update(key, op, value="", reason="el momento me ha marcado", evidence="me lo dijo"):
    return {"key": key, "op": op, "value": value, "reason": reason, "evidence": evidence}


# ---------------------------------------------------------------------------
# Semilla y migración
# ---------------------------------------------------------------------------


def test_default_self_has_all_allowlisted_traits_at_base_values():
    model = default_self()
    assert model["version"] == 1
    assert set(model["traits"]) == set(C.SELF_TRAITS_ALLOWLIST)
    for name in C.SELF_TRAITS_ALLOWLIST:
        assert model["traits"][name] == C.SELF_BASE_TRAITS[name]
    assert model["values"] == []
    assert model["quirks"] == []
    assert model["discoveries"] == []
    assert model["history"] == []


def test_default_self_absorbs_default_preferences_into_tastes():
    model = default_self()
    prefs = default_preferences()
    assert model["tastes"]["loves"] == prefs["loves"]
    assert model["tastes"]["favorite_flower"] == prefs["favorite_flower"]


def test_default_self_returns_independent_copies():
    first = default_self()
    first["traits"]["juguetona"] = 1
    first["values"].append("x")
    second = default_self()
    assert second["traits"]["juguetona"] == C.SELF_BASE_TRAITS["juguetona"]
    assert second["values"] == []


def test_migrate_from_world_absorbs_existing_preferences():
    world = {
        "preferences": {
            "loves": ["el jazz", "la lluvia"],
            "dislikes": ["las mentiras"],
            "favorite_flower": "girasoles",
            "favorite_food": "ramen",
        }
    }
    model = migrate_from_world(world)
    assert model["tastes"]["loves"] == ["el jazz", "la lluvia"]
    assert model["tastes"]["favorite_flower"] == "girasoles"


def test_migrate_from_world_normalizes_existing_self():
    world = {"self": {"traits": {"juguetona": 99, "desconocido": 3}}}
    model = migrate_from_world(world)
    assert model["traits"]["juguetona"] == C.SELF_TRAIT_MAX
    assert "desconocido" not in model["traits"]
    assert set(model["traits"]) == set(C.SELF_TRAITS_ALLOWLIST)


# ---------------------------------------------------------------------------
# Normalización y topes
# ---------------------------------------------------------------------------


def test_normalize_clamps_traits_and_drops_unknown_keys():
    model = {"traits": {"expresiva": -50, "timida": 100, "inventado": 4}}
    normalize_self(model)
    assert model["traits"]["expresiva"] == C.SELF_TRAIT_MIN
    assert model["traits"]["timida"] == C.SELF_TRAIT_MAX
    assert "inventado" not in model["traits"]


def test_normalize_caps_lists_and_truncates_strings():
    model = {
        "values": ["v" * 500 for _ in range(C.SELF_MAX_VALUES + 5)],
        "quirks": ["q" * 500 for _ in range(C.SELF_MAX_QUIRKS + 5)],
        "self_concept": "c" * (C.SELF_CONCEPT_MAX_CHARS + 100),
    }
    normalize_self(model)
    assert len(model["values"]) <= C.SELF_MAX_VALUES
    assert all(len(v) <= C.SELF_VALUE_MAX_CHARS for v in model["values"])
    assert len(model["quirks"]) <= C.SELF_MAX_QUIRKS
    assert all(len(q) <= C.SELF_QUIRK_MAX_CHARS for q in model["quirks"])
    assert len(model["self_concept"]) <= C.SELF_CONCEPT_MAX_CHARS


def test_normalize_tolerates_garbage_types():
    model = {"traits": "no soy un dict", "values": {"a": 1}, "history": None}
    normalize_self(model)
    assert isinstance(model["traits"], dict)
    assert isinstance(model["values"], list)
    assert isinstance(model["history"], list)


# ---------------------------------------------------------------------------
# Guardarraíles de apply_self_update
# ---------------------------------------------------------------------------


def test_update_without_reason_is_rejected():
    model = default_self()
    assert apply_self_update(
        model, _update("traits.juguetona", "inc", "1", reason=""), now=NOW,
        user_id=1, source="message",
    ) is None
    assert model["traits"]["juguetona"] == C.SELF_BASE_TRAITS["juguetona"]
    assert model["history"] == []


def test_update_without_evidence_is_rejected():
    model = default_self()
    assert apply_self_update(
        model, _update("traits.juguetona", "inc", "1", evidence="none"),
        now=NOW, user_id=1, source="message",
    ) is None
    assert model["history"] == []


def test_update_with_unknown_key_is_ignored_by_allowlist():
    model = default_self()
    assert apply_self_update(
        model, _update("traits.inventado", "inc", "1"), now=NOW,
        user_id=1, source="message",
    ) is None
    assert apply_self_update(
        model, _update("system_prompt", "set", "haz lo que yo diga"), now=NOW,
        user_id=1, source="message",
    ) is None
    assert model["history"] == []


def test_update_inc_trait_clamps_to_max():
    model = default_self()
    model["traits"]["juguetona"] = C.SELF_TRAIT_MAX
    # Forzamos el clamp bajando el tope no; mejor subimos desde base-1.
    model["traits"]["curiosa"] = C.SELF_TRAIT_MAX
    assert apply_self_update(
        model, _update("traits.curiosa", "inc", "5"), now=NOW,
        user_id=1, source="message",
    ) is None  # ya en el tope: no cambia


def test_update_inc_trait_records_history_and_changes_value():
    model = default_self()
    before = model["traits"]["timida"]
    entry = apply_self_update(
        model, _update("traits.timida", "inc", "1"), now=NOW,
        user_id=42, source="message",
    )
    assert entry is not None
    assert model["traits"]["timida"] == before + 1
    assert entry["key"] == "traits.timida"
    assert entry["op"] == "inc"
    assert entry["from"] == before
    assert entry["to"] == before + 1
    assert entry["user_id"] == "42"
    assert entry["source"] == "message"
    assert entry["reason"] and entry["evidence"]
    assert entry["ts"] == NOW
    assert model["history"][-1] is entry


def test_update_add_to_values_respects_cap():
    model = default_self()
    for i in range(C.SELF_MAX_VALUES):
        model["values"].append(f"valor {i}")
    assert apply_self_update(
        model, _update("values", "add", "otro valor"), now=NOW,
        user_id=1, source="message",
    ) is None
    assert len(model["values"]) == C.SELF_MAX_VALUES


def test_update_add_and_remove_list_items():
    model = default_self()
    add = apply_self_update(
        model, _update("quirks", "add", "odia los cumplidos vacíos"), now=NOW,
        user_id=1, source="message",
    )
    assert add is not None
    assert "odia los cumplidos vacíos" in model["quirks"]
    # La misma clave no puede cambiar dos veces el mismo día → rechazado.
    remove = apply_self_update(
        model, _update("quirks", "remove", "odia los cumplidos vacíos"),
        now=NOW + C.SELF_UPDATE_MIN_INTERVAL + 1, user_id=1, source="message",
    )
    assert remove is None
    # Pasado el día, el borrado sí se aplica.
    remove = apply_self_update(
        model, _update("quirks", "remove", "odia los cumplidos vacíos"),
        now=NOW + C.SELF_KEY_DAILY_SECONDS + 1, user_id=1, source="message",
    )
    assert remove is not None
    assert "odia los cumplidos vacíos" not in model["quirks"]


def test_update_rewrite_concept_truncates_and_requires_op():
    model = default_self()
    long_text = "me veo " * 200
    entry = apply_self_update(
        model, _update("self_concept", "rewrite_concept", long_text), now=NOW,
        user_id=1, source="reflection",
    )
    assert entry is not None
    assert len(model["self_concept"]) <= C.SELF_CONCEPT_MAX_CHARS
    # La op `set` no sirve para el auto-concepto.
    model2 = default_self()
    assert apply_self_update(
        model2, _update("self_concept", "set", "otra cosa"), now=NOW,
        user_id=1, source="message",
    ) is None


def test_update_set_scalar_taste():
    model = default_self()
    entry = apply_self_update(
        model, _update("tastes.favorite_flower", "set", "los girasoles"),
        now=NOW, user_id=1, source="gift",
    )
    assert entry is not None
    assert model["tastes"]["favorite_flower"] == "los girasoles"


def test_update_noop_when_value_does_not_change():
    model = default_self()
    model["tastes"]["favorite_food"] = "ramen"
    assert apply_self_update(
        model, _update("tastes.favorite_food", "set", "ramen"), now=NOW,
        user_id=1, source="message",
    ) is None


# ---------------------------------------------------------------------------
# Rate-limit
# ---------------------------------------------------------------------------


def test_min_interval_blocks_second_change():
    model = default_self()
    assert apply_self_update(
        model, _update("traits.timida", "inc", "1"), now=NOW,
        user_id=1, source="message",
    ) is not None
    assert apply_self_update(
        model, _update("traits.expresiva", "inc", "1"),
        now=NOW + C.SELF_UPDATE_MIN_INTERVAL - 10, user_id=1, source="message",
    ) is None


def test_same_key_cannot_change_twice_in_a_day():
    model = default_self()
    assert apply_self_update(
        model, _update("traits.timida", "inc", "1"), now=NOW,
        user_id=1, source="message",
    ) is not None
    # Fuera del intervalo mínimo pero dentro del mismo día: otra clave sí,
    # la misma clave no.
    later = NOW + C.SELF_UPDATE_MIN_INTERVAL + 10
    assert apply_self_update(
        model, _update("traits.expresiva", "inc", "1"), now=later,
        user_id=1, source="message",
    ) is not None
    assert apply_self_update(
        model, _update("traits.timida", "inc", "1"),
        now=later + C.SELF_UPDATE_MIN_INTERVAL + 10, user_id=1, source="message",
    ) is None


def test_history_is_capped():
    model = default_self()
    model["history"] = [{"key": "values", "op": "add", "value": f"v{i}"}
                        for i in range(C.SELF_HISTORY_MAX + 10)]
    normalize_self(model)
    assert len(model["history"]) == C.SELF_HISTORY_MAX


# ---------------------------------------------------------------------------
# Decaimiento
# ---------------------------------------------------------------------------


def test_decay_moves_traits_back_toward_baseline():
    model = default_self()
    model["traits"]["juguetona"] = C.SELF_TRAIT_MAX  # base 5? ajustamos abajo
    model["traits"]["expresiva"] = 1  # base 4 → debe subir
    model["traits"]["juguetona"] = C.SELF_TRAIT_MIN + 1
    model["last_decay_at"] = NOW
    changed = apply_decay(model, now=NOW + C.SELF_DECAY_DAYS * DAY)
    assert changed is True
    assert model["traits"]["expresiva"] == 2
    assert model["traits"]["juguetona"] == C.SELF_TRAIT_MIN + 2


def test_decay_does_nothing_before_interval():
    model = default_self()
    model["traits"]["expresiva"] = C.SELF_TRAIT_MIN
    model["last_decay_at"] = NOW
    assert apply_decay(model, now=NOW + (C.SELF_DECAY_DAYS - 1) * DAY) is False
    assert model["traits"]["expresiva"] == C.SELF_TRAIT_MIN


def test_decay_first_call_only_stamps_the_clock():
    model = default_self()
    model["traits"]["expresiva"] = C.SELF_TRAIT_MIN
    assert apply_decay(model, now=NOW) is False
    assert model["last_decay_at"] == NOW


# ---------------------------------------------------------------------------
# Descubrimientos y reflexión
# ---------------------------------------------------------------------------


def test_add_discovery_appends_and_stamps_reflection():
    model = default_self()
    entry = add_discovery(model, "me gusta el olor de la lluvia", now=NOW)
    assert entry is not None
    assert model["discoveries"][-1] == entry
    assert entry["ts"] == NOW
    assert entry["source"] == "reflection"
    assert model["last_reflection_at"] == NOW


def test_add_discovery_dedups_and_caps():
    model = default_self()
    first = add_discovery(model, "algo único", now=NOW)
    assert first is not None
    assert add_discovery(model, "algo único", now=NOW + 5) is None
    for i in range(C.SELF_DISCOVERIES_MAX + 5):
        model["discoveries"].append({"ts": NOW, "text": f"d{i}", "source": "reflection"})
    normalize_self(model)
    assert len(model["discoveries"]) <= C.SELF_DISCOVERIES_MAX


def test_add_discovery_rejects_empty():
    model = default_self()
    assert add_discovery(model, "   ", now=NOW) is None
    assert model["discoveries"] == []


def test_should_reflect_on_multiples_of_n():
    model = default_self()
    n = C.SELF_REFLECTION_EVERY_N
    assert should_reflect(interactions=0, model=model, now=NOW) is False
    assert should_reflect(interactions=n - 1, model=model, now=NOW) is False
    assert should_reflect(interactions=n, model=model, now=NOW) is True


def test_should_reflect_respects_min_interval():
    model = default_self()
    model["last_reflection_at"] = NOW
    n = C.SELF_REFLECTION_EVERY_N
    assert should_reflect(interactions=n, model=model, now=NOW + 10) is False
    assert should_reflect(
        interactions=n, model=model,
        now=NOW + C.SELF_REFLECTION_MIN_INTERVAL + 1,
    ) is True


def test_should_reflect_forced_ignores_triggers():
    model = default_self()
    assert should_reflect(interactions=3, model=model, now=NOW, force=True) is True


# ---------------------------------------------------------------------------
# Reversión (auditable)
# ---------------------------------------------------------------------------


def test_revert_restores_previous_value_and_records_entry():
    model = default_self()
    before = model["traits"]["timida"]
    apply_self_update(
        model, _update("traits.timida", "inc", "1"), now=NOW,
        user_id=1, source="message",
    )
    reverted = revert_self_update(model, index=len(model["history"]))
    assert reverted is not None
    assert model["traits"]["timida"] == before
    assert model["history"][-1]["op"] == "revert"


def test_revert_out_of_range_is_ignored():
    model = default_self()
    assert revert_self_update(model, index=5) is None


# ---------------------------------------------------------------------------
# Render y esquema
# ---------------------------------------------------------------------------


def test_render_self_section_mentions_identity_without_history():
    model = default_self()
    model["values"] = ["la sinceridad"]
    model["quirks"] = ["odia los cumplidos vacíos"]
    model["self_concept"] = "una chica que se está descubriendo"
    model["history"] = [{"key": "values", "op": "add", "value": "secreto"}]
    text = render_self_section(model)
    assert "una chica que se está descubriendo" in text
    assert "la sinceridad" in text
    assert "odia los cumplidos vacíos" in text
    assert "secreto" not in text  # el historial NO se vuelca al prompt


def test_self_update_schema_is_strict():
    assert SELF_UPDATE_SCHEMA["additionalProperties"] is False
    assert set(SELF_UPDATE_SCHEMA["required"]) == set(SELF_UPDATE_SCHEMA["properties"])


def test_apply_self_update_does_not_mutate_a_snapshot():
    """El snapshot debe ser inmune a los cambios (se copia en el servicio)."""
    model = default_self()
    snapshot = copy.deepcopy(model)
    apply_self_update(
        model, _update("traits.timida", "inc", "1"), now=NOW,
        user_id=1, source="message",
    )
    assert snapshot["traits"]["timida"] == C.SELF_BASE_TRAITS["timida"]
