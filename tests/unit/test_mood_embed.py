"""El ánimo se publica en el embed del turno y en `!yo`."""

from __future__ import annotations

import asyncio

from airi.discord_bot.turn import mood_summary, send_gif_bytes
from airi.domain.self_model import render_self_narrative
from airi.testing import FakeUser, make_state

MOOD = {
    "label": "juguetona",
    "valence": 2,
    "energy": 4,
    "warmth": 3,
    "categories": {
        "entusiasmo": 4,
        "tension": 2,
        "calma": 0,
        "bajon": 0,
        "neutral": 0,
    },
    "cause": "broma compartida",
    "user_id": "42",
}


class FakeChannel:
    def __init__(self):
        self.embeds = []

    async def send(self, *, embed=None, **kwargs):
        self.embeds.append(embed)


class FakeCtx:
    def __init__(self, state):
        self.state = state

    def affinity_footer(self, user):
        return ""


def _state_with_mood():
    state, _ = make_state()
    state.world["mood"] = dict(MOOD)
    return state


def test_mood_summary_shows_categories_with_bars():
    text = mood_summary(FakeCtx(_state_with_mood()))
    assert "Entusiasmo" in text
    assert "4/5" in text
    assert "Tensión" in text
    assert "2/5" in text
    assert "valencia" not in text
    assert "energía" not in text
    assert "cercanía" not in text
    assert "broma compartida" not in text


def test_mood_summary_is_empty_without_mood():
    state, _ = make_state()
    assert mood_summary(FakeCtx(state)) == ""


def test_mood_summary_is_empty_when_disabled(monkeypatch):
    import airi.discord_bot.turn as turn

    monkeypatch.setattr(turn, "MOOD_ENABLED", False)
    assert mood_summary(FakeCtx(_state_with_mood())) == ""


def test_turn_embed_shows_mood_below_traits():
    state = _state_with_mood()
    channel = FakeChannel()
    asyncio.run(
        send_gif_bytes(
            FakeCtx(state),
            channel,
            FakeUser(42, "David"),
            "happy",
            None,
        )
    )
    embed = channel.embeds[0]
    names = [field.name for field in embed.fields]
    assert "Rasgos de Airi" in names
    assert "Ánimo de Airi" in names
    assert names.index("Ánimo de Airi") == names.index("Rasgos de Airi") + 1
    assert embed.color.value == 0xF5C542
    trait_field = next(field for field in embed.fields if field.name == "Rasgos de Airi")
    assert "Expresividad" in trait_field.value
    assert "████" in trait_field.value


def test_self_narrative_shows_mood_after_traits():
    state = _state_with_mood()
    text = render_self_narrative(
        state.self_model(),
        notes=[],
        preferences=state.world.get("preferences"),
        mood=state.world.get("mood"),
    )
    assert "**Mis rasgos:**" in text
    assert "Expresividad" in text
    assert "████" in text
    assert "**Mi ánimo ahora:** Entusiasmo" in text
    assert "4/5" in text
    assert text.index("**Mi ánimo ahora:**") > text.index("**Mis rasgos:**")
