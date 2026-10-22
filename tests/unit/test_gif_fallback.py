"""Respaldo de GIF: todo turno debe llevar una emoción válida."""

from airi.services.conversation import guaranteed_gif


def test_valid_gif_is_preserved():
    assert guaranteed_gif("shy", "Conocida") == "shy"


def test_none_uses_happy_for_neutral_affinity():
    assert guaranteed_gif("none", "Desconocida") == "happy"


def test_none_uses_nope_for_negative_affinity():
    assert guaranteed_gif("none", "Enfadada") == "nope"


def test_invalid_gif_uses_fallback():
    assert guaranteed_gif("emoji", "Amiga") == "happy"
    assert guaranteed_gif(None, "Distante") == "nope"
