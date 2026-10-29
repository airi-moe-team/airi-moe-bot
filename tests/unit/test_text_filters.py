"""Tests de los filtros de texto de las respuestas del modelo."""

from __future__ import annotations

from airi.domain.text_filters import clean_reply, limit_narrative_actions


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


# --- artefactos de plantilla ------------------------------------------------


def test_clean_reply_elimina_marcas_de_plantilla():
    assert clean_reply("Hola<|im_end|>") == "Hola"
    assert clean_reply("<|im_start|>Hola") == "Hola"
    assert clean_reply("Hola</s>") == "Hola"
    assert clean_reply("Hola<|endoftext|>") == "Hola"


def test_clean_reply_elimina_prefijos_de_rol_al_inicio_de_linea():
    assert clean_reply("User: hola") == "hola"
    assert clean_reply("Assistant: ¿qué tal?") == "¿qué tal?"
    assert clean_reply("### Human:\nhola") == "hola"
    assert clean_reply("### Assistant:\n¿qué tal?") == "¿qué tal?"


def test_clean_reply_no_toca_el_rol_a_mitad_de_frase():
    assert clean_reply("Le dije a User: hola") == "Le dije a User: hola"
