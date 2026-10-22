"""Tests de la UI de la cita (views.date + embeds.scene_select_embed).

Cuban la formateo de etiquetas, la construcción del selector de escena y el
embed, sin tocar red ni Discord real.
"""

import discord

from airi.discord_bot import embeds
from airi.discord_bot.views import date as date_views
from airi.discord_bot.views.date import SceneSelectView, scene_label


def _labels(view):
    return [child.label for child in view.children]


def _emojis(view):
    # discord.py normaliza el emoji a PartialEmoji; str() devuelve su nombre.
    return [str(child.emoji) for child in view.children]


def _payloads(view):
    return [child.payload for child in view.children]


def _styles(view):
    return [child.style for child in view.children]


def _make_view(scenes):
    return SceneSelectView(
        owner_id=1,
        scenes=scenes,
        on_choice=lambda *args: None,
        timeout=120,
    )


# --- scene_label ---------------------------------------------------------


def test_scene_label_capitalizes_first_letter():
    assert scene_label("un paseo") == "Un paseo"


def test_scene_label_collapses_spaces_and_newlines():
    assert scene_label("  un   paseo\npor el   parque  ") == "Un paseo por el parque"


def test_scene_label_does_not_lowercase_proper_nouns():
    # Solo se capitaliza la inicial; el resto se deja tal cual.
    assert scene_label("visita a PARIS y ROMA") == "Visita a PARIS y ROMA"


def test_scene_label_truncates_with_ellipsis_within_limit():
    long = "una escena muy larga que se queda muy lejos del limite"
    result = scene_label(long)
    assert result.endswith("…")
    assert len(result) <= date_views.DATE_SCENE_LABEL_MAX


def test_scene_label_truncates_on_word_boundary():
    assert scene_label("Cena romántica a la luz de las velas") == "Cena romántica a la luz…"


def test_scene_label_drops_trailing_stopword():
    assert scene_label("Feria con luces de colores y algodón dulce") == "Feria con luces de colores…"


def test_scene_label_truncates_long_single_word():
    word = "x" * 60
    result = scene_label(word)
    assert result.endswith("…")
    assert len(result) <= date_views.DATE_SCENE_LABEL_MAX


def test_scene_label_custom_limit():
    assert scene_label("hola mundo", limit=5) == "Hola…"


def test_scene_label_returns_empty_for_empty_or_none():
    assert scene_label("") == ""
    assert scene_label(None) == ""


# --- SceneSelectView -----------------------------------------------------


def test_scene_select_view_three_scenes():
    scenes = ["un paseo", "una cena", "un cine"]
    view = _make_view(scenes)

    assert len(view.children) == 4
    assert _labels(view) == ["Un paseo", "Una cena", "Un cine", "Sorpréndeme"]
    assert _emojis(view) == ["🕯️", "🍿", "🎡", "🎲"]
    assert _styles(view) == [
        discord.ButtonStyle.primary,
        discord.ButtonStyle.primary,
        discord.ButtonStyle.primary,
        discord.ButtonStyle.secondary,
    ]
    # El payload de los planes es la escena ORIGINAL (sin formatear).
    assert _payloads(view)[:3] == scenes
    assert _payloads(view)[3] is None


def test_scene_select_view_five_scenes_caps_at_three_plans():
    scenes = ["a", "b", "c", "d", "e"]
    view = _make_view(scenes)

    assert len(view.children) == 4
    # Los 3 primeros planes usan las 3 primeras escenas; el último es la sorpresa.
    assert _payloads(view)[:3] == scenes[:3]
    assert _payloads(view)[3] is None


def test_scene_select_view_zero_scenes_only_surprise():
    view = _make_view([])

    assert len(view.children) == 1
    assert _labels(view) == ["Sorpréndeme"]
    assert _payloads(view) == [None]
    assert _emojis(view) == ["🎲"]


# --- scene_select_embed --------------------------------------------------


def test_scene_select_embed_title_description_and_color():
    embed = embeds.scene_select_embed(date_views.DATE_EMBED_COLOR)

    assert embed.title == "🌹 ¿Adónde la llevas?"
    assert embed.description == "👇 Elige un plan o déjate llevar por el azar."
    assert embed.color.value == 0xF472B6


# --- build_date_embed (turnos + tiempo restante) --------------------------


def _footer(embed):
    return embed.footer.text if embed.footer is not None else None


def test_build_date_embed_shows_turns_and_remaining_time():
    embed = date_views.build_date_embed(
        "Te sonríe.",
        scene="un paseo por el parque",
        state="active",
        turns_left=3,
        seconds_left=240,
    )

    assert _footer(embed) == "Turnos restantes: 3 · ⏳ ~4 min"
    assert embed.title == "🌹 Cita · un paseo por el parque"
    assert embed.description == "Te sonríe."


def test_build_date_embed_time_under_a_minute():
    embed = date_views.build_date_embed(
        "Te sonríe.", turns_left=6, seconds_left=10
    )

    assert _footer(embed) == "Turnos restantes: 6 · ⏳ <1 min"


def test_build_date_embed_without_time_keeps_old_footer():
    # Retrocompatibilidad: sin seconds_left no se muestra tiempo.
    embed = date_views.build_date_embed("Hola.", turns_left=2)

    assert _footer(embed) == "Turnos restantes: 2"


def test_build_date_embed_without_turns_shows_only_time():
    embed = date_views.build_date_embed("Hola.", seconds_left=125)

    assert _footer(embed) == "⏳ ~3 min"


def test_build_date_embed_no_footer_when_nothing_to_show():
    embed = date_views.build_date_embed("Hola.", state="active")

    assert _footer(embed) is None


def test_build_date_embed_last_chance_and_time():
    embed = date_views.build_date_embed(
        "Se tuerce.", state="last_chance", turns_left=1, seconds_left=45
    )

    assert _footer(embed) == "Última oportunidad · Turnos restantes: 1 · ⏳ <1 min"


# --- DateQuestionView (pregunta decisiva) ----------------------------------


OPTIONS = [
    {"label": "Tu risa", "action": "le digo que su risa"},
    {"label": "Tu compañía", "action": "le digo que su compañía"},
]


def _question_view(options=None, **kw):
    return date_views.DateQuestionView(
        owner_id=1,
        options=OPTIONS if options is None else options,
        on_choice=lambda *args: None,
        **kw,
    )


def test_build_question_embed_title_description_and_color():
    embed = date_views.build_question_embed("¿Qué es lo que más te gusta de mí?")

    assert embed.title == "💞 Airi te pregunta algo importante"
    assert embed.description == "¿Qué es lo que más te gusta de mí?"
    assert embed.color.value == 0xF472B6


def test_build_question_embed_empty_text_placeholder():
    embed = date_views.build_question_embed("")

    assert embed.description == "…"


def test_date_question_view_three_buttons_with_labels_and_emojis():
    view = _question_view()

    assert len(view.children) == 2
    assert _labels(view) == ["Tu risa", "Tu compañía"]
    assert _emojis(view) == ["💗", "✨"]
    # El payload es el ÍNDICE de la opción en la sesión.
    assert _payloads(view) == [0, 1]


def test_date_question_view_caps_at_max_options():
    five = [dict(OPTIONS[0], label=f"Opción {i}") for i in range(5)]
    view = _question_view(five)

    assert len(view.children) == 3


def test_date_question_view_falls_back_to_action_and_index_label():
    view = _question_view([{"action": "haces algo"}, {}])

    assert _labels(view) == ["haces algo", "Opción 2"]
    assert _payloads(view) == [0, 1]


def test_date_question_view_labels_clamped_to_discord_limit():
    long_label = "x" * 120
    view = _question_view([{"label": long_label, "action": "y"}])

    assert len(_labels(view)[0]) <= 80
