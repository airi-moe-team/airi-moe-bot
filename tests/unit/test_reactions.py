"""Detección de negaciones y correcciones directas."""

from __future__ import annotations

from airi.domain.reactions import is_negative_reaction


def test_no_repetido_es_negacion():
    assert is_negative_reaction("noooooooo") is True
    assert is_negative_reaction("no") is True
    assert is_negative_reaction("¡No!") is True


def test_desacuerdo_directo_es_negacion():
    assert is_negative_reaction("otra vez estás equivocada") is True
    assert is_negative_reaction("te equivocas, no es así") is True


def test_opinion_normal_no_es_negacion():
    assert is_negative_reaction("no me gusta el anime") is False
    assert is_negative_reaction("no es que no me guste, pero prefiero el té") is False
