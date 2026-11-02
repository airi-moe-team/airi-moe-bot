"""Categorías de ánimo: cuadrantes, coexistencia y barras."""

from __future__ import annotations

from airi.domain.mood import (
    MOOD_CATEGORIES,
    apply_mood,
    blend_mood,
    categories_from_axes,
    mood_primary_category,
    mood_visible_categories,
    normalize_categories,
    normalize_mood,
    render_mood_bar,
    render_mood_history,
    render_mood_meter,
    render_mood_sparkline,
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


def _mood(categories, *, valence=2, energy=4, warmth=3, label="alegre"):
    return {
        "label": label,
        "valence": valence,
        "energy": energy,
        "warmth": warmth,
        "categories": categories,
        "cause": "none",
        "updated_at": NOW - 60,
    }


def test_categories_from_axes_maps_the_four_quadrants():
    assert mood_primary_category(
        {"categories": categories_from_axes(2, 5)}
    ) == "entusiasmo"
    assert mood_primary_category(
        {"categories": categories_from_axes(1, 2)}
    ) == "calma"
    assert mood_primary_category(
        {"categories": categories_from_axes(-2, 5)}
    ) == "tension"
    assert mood_primary_category(
        {"categories": categories_from_axes(-1, 1)}
    ) == "bajon"
    assert mood_primary_category(
        {"categories": categories_from_axes(0, 3)}
    ) == "neutral"


def test_normalize_categories_clamps_and_accepts_synonyms():
    categories = normalize_categories(
        {"estrés": 99, "Euforia": 3, "tristeza": -4, "basura": 5}
    )
    assert set(categories) == set(MOOD_CATEGORIES)
    assert categories["tension"] == 5
    assert categories["entusiasmo"] == 3
    assert categories["bajon"] == 0
    assert sum(categories.values()) == 8


def test_normalize_mood_keeps_declared_coexisting_categories():
    mood = normalize_mood(
        _mood({"entusiasmo": 4, "tension": 2, "calma": 0, "bajon": 0, "neutral": 0})
    )
    assert mood["categories"]["entusiasmo"] == 4
    assert mood["categories"]["tension"] == 2
    assert mood_primary_category(mood) == "entusiasmo"


def test_blend_mood_moves_each_category_at_most_one_step():
    previous = _mood(
        {"entusiasmo": 5, "tension": 0, "calma": 0, "bajon": 0, "neutral": 0}
    )
    proposed = _mood(
        {"entusiasmo": 0, "tension": 4, "calma": 0, "bajon": 0, "neutral": 0},
        valence=-2,
        label="molesta",
    )
    blended = blend_mood(previous, proposed, now=NOW)
    assert blended["categories"]["entusiasmo"] == 4
    assert blended["categories"]["tension"] == 1


def test_visible_categories_shows_primary_and_strong_secondary():
    mood = _mood(
        {"entusiasmo": 4, "tension": 2, "calma": 1, "bajon": 0, "neutral": 0}
    )
    visible = mood_visible_categories(mood)
    assert [key for key, _ in visible] == ["entusiasmo", "tension"]


def test_visible_categories_hides_weak_secondary():
    mood = _mood(
        {"entusiasmo": 4, "tension": 1, "calma": 0, "bajon": 0, "neutral": 0}
    )
    visible = mood_visible_categories(mood)
    assert [key for key, _ in visible] == ["entusiasmo"]


def test_visible_categories_falls_back_to_neutral():
    mood = _mood(
        {"entusiasmo": 0, "tension": 0, "calma": 0, "bajon": 0, "neutral": 0}
    )
    assert mood_visible_categories(mood) == [("neutral", 3)]


def test_render_mood_bar_fills_proportionally():
    assert "██████████ 5/5" in render_mood_bar("entusiasmo", 5)
    assert "██░░░░░░░░ 1/5" in render_mood_bar("entusiasmo", 1)
    assert "░░░░░░░░░░ 0/5" in render_mood_bar("entusiasmo", 0)
    assert "Entusiasmo" in render_mood_bar("entusiasmo", 3)


def test_render_mood_bar_respects_width():
    assert render_mood_bar("calma", 3, width=4).count("█") == 2
    assert render_mood_bar("calma", 3, width=4).count("░") == 2


def test_render_mood_meter_marks_primary_change():
    previous = _mood(
        {"entusiasmo": 0, "tension": 0, "calma": 4, "bajon": 0, "neutral": 0}
    )
    current = _mood(
        {"entusiasmo": 4, "tension": 2, "calma": 0, "bajon": 0, "neutral": 0}
    )
    text = render_mood_meter(current, previous=previous)
    assert "Entusiasmo" in text
    assert "Tensión" in text
    assert "(antes: Calma)" in text


def test_render_mood_meter_omits_change_when_primary_is_stable():
    previous = _mood(
        {"entusiasmo": 3, "tension": 0, "calma": 0, "bajon": 0, "neutral": 0}
    )
    current = _mood(
        {"entusiasmo": 4, "tension": 0, "calma": 0, "bajon": 0, "neutral": 0}
    )
    assert "antes:" not in render_mood_meter(current, previous=previous)


def test_render_mood_sparkline_uses_category_emoji():
    history = [
        _mood({"entusiasmo": 4, "tension": 0, "calma": 0, "bajon": 0, "neutral": 0}),
        _mood({"entusiasmo": 0, "tension": 0, "calma": 0, "bajon": 4, "neutral": 0}),
    ]
    assert render_mood_sparkline(history) == "🟡 ⚫"
    assert render_mood_sparkline([]) == ""


def test_history_shows_categories_without_axes():
    world = {}
    apply_mood(
        world,
        _mood(
            {"entusiasmo": 4, "tension": 2, "calma": 0, "bajon": 0, "neutral": 0}
        ),
        now=NOW,
        traits=TRAITS,
    )
    text = render_mood_history(world)
    assert "Entusiasmo" in text
    assert "Tensión" in text
    assert "valencia" not in text
    assert "Evolución" in text


def test_old_mood_without_categories_migrates_from_axes():
    mood = normalize_mood(
        {
            "label": "melancolica",
            "valence": -2,
            "energy": 2,
            "warmth": 2,
        }
    )
    assert "categories" in mood
    assert mood_primary_category(mood) == "bajon"
