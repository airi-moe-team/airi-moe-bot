"""Ánimo transitorio: normalización, inercia, base y render."""

from __future__ import annotations

from airi.domain.mood import (
    MOOD_LABELS,
    apply_mood,
    baseline_mood,
    blend_mood,
    label_for_axes,
    normalize_history,
    normalize_label,
    normalize_mood,
    render_mood_history,
    render_mood_section,
)

NOW = 1_000_000.0

TRAITS = {
    "expresiva": 4,
    "timida": 3,
    "juguetona": 5,
    "celosa": 2,
    "sarcastica": 2,
    "curiosa": 4,
}


def test_normalize_label_accepts_accents_and_synonyms():
    assert normalize_label("Alegría") == "alegre"
    assert normalize_label("timída") == "timida"
    assert normalize_label("feliz") == "alegre"
    assert normalize_label("ENFADADA") == "molesta"
    assert normalize_label("none") == ""


def test_normalize_mood_accepts_a_bare_label():
    mood = normalize_mood("melancólica")
    assert mood["label"] == "melancolica"
    assert mood["valence"] == -2
    assert mood["cause"] == "none"


def test_normalize_mood_clamps_axes_and_cleans_cause():
    mood = normalize_mood(
        {
            "label": "molesta",
            "valence": -99,
            "energy": 99,
            "warmth": "0",
            "cause": "  me   ignoró  ",
        }
    )
    assert mood["valence"] == -2
    assert mood["energy"] == 5
    assert mood["warmth"] == 1
    assert mood["cause"] == "me ignoró"


def test_normalize_mood_rejects_unusable_payloads():
    assert normalize_mood(None) is None
    assert normalize_mood({}) is None
    assert normalize_mood({"label": "none"}) is None
    assert normalize_mood({"cause": "sin ejes"}) is None


def test_normalize_mood_derives_label_from_axes():
    mood = normalize_mood({"valence": 2, "energy": 4, "warmth": 4})
    assert mood["label"] == label_for_axes(2, 4, 4)
    assert mood["label"] in MOOD_LABELS


def test_baseline_is_deterministic_and_low_energy_at_night():
    day = baseline_mood(TRAITS, now=NOW, hour=12)
    night = baseline_mood(TRAITS, now=NOW, hour=2)
    assert day == baseline_mood(TRAITS, now=NOW, hour=12)
    assert night["energy"] <= day["energy"]
    assert day["valence"] >= -2


def test_blend_mood_moves_at_most_one_step_per_turn():
    previous = {
        "label": "alegre",
        "valence": 2,
        "energy": 4,
        "warmth": 4,
        "cause": "none",
        "updated_at": NOW - 60,
    }
    proposed = normalize_mood("melancolica")
    blended = blend_mood(previous, proposed, now=NOW)
    assert blended["label"] == "melancolica"
    assert blended["valence"] == 1
    assert blended["energy"] == 3
    assert blended["warmth"] == 3


def test_blend_mood_resets_stale_state_to_baseline():
    previous = {
        "label": "molesta",
        "valence": -2,
        "energy": 3,
        "warmth": 1,
        "cause": "none",
        "updated_at": NOW - 7 * 3600,
    }
    baseline = baseline_mood(TRAITS, now=NOW, hour=12)
    blended = blend_mood(previous, "tranquila", now=NOW, baseline=baseline)
    # Al estar caducado, no arrastra la valencia negativa del estado viejo.
    assert blended["valence"] >= baseline["valence"] - 1
    assert blended["warmth"] >= baseline["warmth"] - 1


def test_apply_mood_persists_current_and_history():
    world = {}
    mood, source = apply_mood(
        world,
        {"label": "juguetona", "cause": "broma"},
        now=NOW,
        user_id=42,
        channel_id=7,
        traits=TRAITS,
    )
    assert source == "model"
    assert mood["label"] == "juguetona"
    assert world["mood"]["user_id"] == "42"
    assert len(world["mood_history"]) == 1

    apply_mood(world, None, now=NOW + 60, user_id=42, traits=TRAITS)
    assert len(world["mood_history"]) == 2
    assert world["mood_history"][-1]["source"] == "fallback"


def test_apply_mood_caps_history():
    world = {}
    for i in range(60):
        apply_mood(world, "neutral", now=NOW + i, traits=TRAITS)
    assert len(world["mood_history"]) <= 50


def test_normalize_history_discards_invalid_entries():
    history = normalize_history(
        [
            "basura",
            {"label": "rara"},
            {"label": "alegre", "ts": "x"},
        ]
    )
    assert len(history) == 1
    assert history[0]["label"] == "alegre"
    assert history[0]["ts"] == 0.0


def test_render_mood_section_shows_mood_without_announcing_it():
    mood = normalize_mood("timida")
    text = render_mood_section(
        mood,
        traits=TRAITS,
        affinity_points=30,
        display_name="Ana",
        now=NOW,
    )
    assert "=== ÁNIMO DE ESTE TURNO ===" in text
    assert "timida" in text
    assert "Con Ana" in text
    lowered = text.lower()
    assert "expresa tu ánimo de manera natural a través del tono y la actitud conversacional" in lowered
    assert "no necesitas anunciarlo ni explicarlo" in lowered
    assert "el gif representa una reacción observable coherente con la respuesta" in lowered
    assert "no tiene que coincidir con la etiqueta emocional" in lowered
    assert "la afinidad manda en el trato hacia esta persona" in text
    assert "elige" not in text.lower()


def test_render_mood_section_uses_baseline_when_missing():
    text = render_mood_section(None, traits=TRAITS, now=NOW)
    assert "=== ÁNIMO DE ESTE TURNO ===" in text
    assert any(label in text for label in MOOD_LABELS)


def test_render_mood_history_hides_cause_by_default():
    world = {}
    apply_mood(
        world,
        {"label": "molesta", "cause": "me mintió"},
        now=NOW,
        traits=TRAITS,
    )
    public = render_mood_history(world)
    owner = render_mood_history(world, include_cause=True)
    assert "Tensión" in public
    assert "me mintió" not in public
    assert "me mintió" in owner


def test_render_mood_history_empty_state():
    assert "todavía no ha registrado" in render_mood_history({})
