"""Tests de los constructores de presentación añadidos para separar sistema/LLM.

`system_embed` da formato de embed a los mensajes del sistema; `date_status_embed`
muestra el estado de la cita (sin la respuesta del modelo) en las transiciones.
"""

from airi.discord_bot import embeds
from airi.discord_bot.views import date as date_views


def test_system_embed_uses_system_color_and_description():
    e = embeds.system_embed("Aviso del sistema")

    assert e.description == "Aviso del sistema"
    assert e.color.value == embeds.SYSTEM_EMBED_COLOR.value
    assert e.title is None
    assert e.footer.text is None


def test_system_embed_title_and_footer():
    e = embeds.system_embed("cuerpo", title="Título", footer="pie")

    assert e.title == "Título"
    assert e.footer.text == "pie"


def test_system_embed_empty_description_placeholder():
    assert embeds.system_embed("").description == "…"


def test_date_status_embed_last_chance_footer():
    e = date_views.date_status_embed(
        "un paseo", state="last_chance", turns_left=2, seconds_left=125
    )

    assert e.title == "🌹 Cita · un paseo"
    assert e.footer.text == "Última oportunidad · Turnos restantes: 2 · ⏳ ~3 min"


def test_date_status_embed_closed_footer():
    e = date_views.date_status_embed("cena", state="closed", turns_left=0)

    assert e.footer.text == "Cita finalizada · Turnos restantes: 0"


def test_date_status_embed_active_without_scene_has_no_title():
    e = date_views.date_status_embed("", state="active", turns_left=3)

    assert e.title is None
    assert e.footer.text == "Turnos restantes: 3"
