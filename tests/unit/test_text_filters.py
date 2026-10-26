"""Tests de los filtros de texto de las respuestas del modelo."""

from __future__ import annotations

from airi.domain.text_filters import limit_narrative_actions


def test_limit_narrative_actions_keeps_the_first_action():
    assert (
        limit_narrative_actions("*sonríe* Hola. *se rasca la cabeza*")
        == "*sonríe* Hola."
    )


def test_limit_narrative_actions_does_not_touch_replies_with_one_or_none():
    assert limit_narrative_actions("Hola, ¿qué tal?") == "Hola, ¿qué tal?"
    assert limit_narrative_actions("*sonríe* Hola") == "*sonríe* Hola"


def test_limit_narrative_actions_cleans_extra_spaces_and_punctuation():
    assert limit_narrative_actions("Hola *a* , *b* mundo") == "Hola *a*, mundo"
