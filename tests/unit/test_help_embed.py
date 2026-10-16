"""Tests del embed de ayuda: la duración de la cita es dinámica.

El `!help` debe reflejar `DATE_MAX_SECONDS` del entorno vigente, no un
literal fijo que se desincronice al cambiar el .env.
"""

import airi.discord_bot.embeds as embeds
from airi.discord_bot.embeds import build_help_embed, date_max_minutes


def test_date_max_minutes_rounds_up():
    # 300 s → 5
    assert date_max_minutes() == 5


def test_help_embed_shows_date_minutes_from_env():
    embed = build_help_embed()

    assert f"(máx. ~{date_max_minutes()} min)" in embed.description
    assert embeds.DATE_HELP_MINUTES_PLACEHOLDER not in embed.description


def test_help_embed_is_dynamic_with_env(monkeypatch):
    import airi.discord_bot.embeds as embeds_module

    monkeypatch.setattr(embeds_module, "DATE_MAX_SECONDS", 600)

    embed = build_help_embed()

    assert "(máx. ~10 min)" in embed.description
