"""Tests de la UI de la cita (views.date).

Cubren la construcción del embed de turnos, el embed de la pregunta decisiva
y el selector de alternativas (DateQuestionView), sin tocar red ni Discord real.
"""

import asyncio

import discord

from airi.discord_bot.views import date as date_views
from airi.discord_bot.views.date import DateQuestionView


def _labels(view):
    return [child.label for child in view.children]


def _emojis(view):
    # discord.py normaliza el emoji a PartialEmoji; str() devuelve su nombre.
    return [str(child.emoji) for child in view.children]


def _payloads(view):
    return [child.payload for child in view.children]


def _styles(view):
    return [child.style for child in view.children]


def _make_view(options, on_choice=None, **kw):
    return DateQuestionView(
        owner_id=1,
        options=options,
        on_choice=on_choice or (lambda *args: None),
        **kw,
    )


OPTIONS = [
    {"label": "Cómo me escuchas", "action": "le escuchas atentamente",
     "up_chance": 0.85, "delta_up": 22, "delta_down": -6},
    {"label": "Eres guapa", "action": "le dices que es guapa",
     "up_chance": 0.30, "delta_up": 6, "delta_down": -18},
    {"label": "No sé...", "action": "dudas y no sabes qué decir",
     "up_chance": 0.55, "delta_up": 12, "delta_down": -12},
]


# --- build_question_embed -------------------------------------------------

def test_build_question_embed_title_and_description():
    embed = date_views.build_question_embed("¿Qué es lo que más te gusta de mí?")

    assert embed.title == "💞 Airi te pregunta algo importante"
    assert embed.description == "¿Qué es lo que más te gusta de mí?"
    assert embed.color.value == 0xF472B6
    assert embed.footer.text == "Elige una respuesta con los botones."


def test_build_question_embed_empty_text_placeholder():
    embed = date_views.build_question_embed("")

    assert embed.description == "…"


# --- DateQuestionView -----------------------------------------------------

def test_date_question_view_three_buttons_with_labels_and_emojis():
    view = _make_view(OPTIONS)

    assert len(view.children) == 3
    assert _labels(view) == ["Cómo me escuchas", "Eres guapa", "No sé..."]
    assert _emojis(view) == ["💗", "✨", "🌙"]
    assert all(style is discord.ButtonStyle.primary for style in _styles(view))


def test_date_question_view_payload_is_option_index():
    # El payload es el ÍNDICE de la opción en la sesión (no el texto).
    view = _make_view(OPTIONS)

    assert _payloads(view) == [0, 1, 2]


def test_date_question_view_caps_at_max_options():
    five = [dict(OPTIONS[0], label=f"Opción {i}") for i in range(5)]

    view = _make_view(five)

    assert len(view.children) == date_views.DATE_QUESTION_OPTIONS


def test_date_question_view_empty_options_has_no_buttons():
    view = _make_view([])

    assert view.children == []


def test_date_question_view_falls_back_to_action_and_index_label():
    view = _make_view([{"action": "haces algo"}, {}])

    assert _labels(view) == ["haces algo", "Opción 2"]


def test_date_question_view_labels_clamped_to_discord_limit():
    long_label = "x" * 120

    view = _make_view([{"label": long_label, "action": "a"}])

    assert len(view.children[0].label) <= date_views.DISCORD_LABEL_MAX
    assert view.children[0].label.endswith("…")



# --- handle_choice (dueño + deshabilitado) --------------------------------

class _FakeInteraction:
    def __init__(self, user_id):
        self.user = discord.Object(id=user_id)
        self.response = self
        self.edited = []
        self.notices = []

    async def edit_message(self, *, view=None, **kw):
        self.edited.append(view)

    async def send_message(self, content=None, *, ephemeral=False, embed=None, **kw):
        self.notices.append((content, ephemeral))


def test_handle_choice_ignores_non_owner():
    seen = []

    async def _on_choice(i, p):
        seen.append(p)

    view = _make_view(OPTIONS, on_choice=_on_choice)
    interaction = _FakeInteraction(user_id=999)

    asyncio.run(view.handle_choice(interaction, 0))

    assert seen == []
    assert interaction.notices  # aviso ephemeral de "no es contigo"


def test_handle_choice_calls_handler_and_disables_buttons():
    seen = []

    async def _on_choice(i, p):
        seen.append(p)

    view = _make_view(OPTIONS, on_choice=_on_choice)
    interaction = _FakeInteraction(user_id=1)

    asyncio.run(view.handle_choice(interaction, 2))

    assert seen == [2]
    assert all(child.disabled for child in view.children)

