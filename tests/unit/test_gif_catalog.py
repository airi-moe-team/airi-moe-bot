"""Catálogo de GIFs: todas las categorías oficiales de NekosBest."""

from airi.domain.gifs import (
    ALLOWED_GIF_TYPES,
    GIF_CATEGORIES,
    GIF_EMOTION_TITLES,
)

# Categorías oficiales de GIF de https://docs.nekos.best.
OFFICIAL_GIF_CATEGORIES = {
    "angry", "baka", "bite", "bleh", "blowkiss", "blush", "bonk", "bored",
    "carry", "clap", "confused", "cry", "cuddle", "dance", "facepalm",
    "feed", "handhold", "handshake", "happy", "highfive", "hug",
    "kabedon", "kick", "kiss", "lappillow", "laugh", "lurk", "nod", "nom",
    "nope", "nya", "pat", "peck", "poke", "pout", "punch", "run",
    "salute", "shake", "shoot", "shocked", "shrug", "sip", "slap",
    "sleep", "smile", "smug", "spin", "stare", "tableflip", "teehee",
    "think", "thumbsup", "tickle", "wag", "wave", "wink", "yawn", "yeet",
}


def test_every_official_category_is_reachable():
    mapped = {category for cats in GIF_CATEGORIES.values() for category in cats}
    assert OFFICIAL_GIF_CATEGORIES <= mapped


def test_every_category_type_is_allowed():
    assert set(GIF_CATEGORIES) <= ALLOWED_GIF_TYPES


def test_every_allowed_type_has_an_embed_title():
    assert ALLOWED_GIF_TYPES - {"none"} <= set(GIF_EMOTION_TITLES)
