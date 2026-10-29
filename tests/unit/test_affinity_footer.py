"""El pie de afinidad se muestra siempre que hay usuario; el delta solo si hubo cambio."""

from __future__ import annotations

from types import SimpleNamespace

from airi.discord_bot.turn import affinity_footer_for_change

BASE = "💛 Afinidad de David: 2 pts · Amiga · ██"
USER = SimpleNamespace(display_name="David")


def _ctx(text=BASE):
    return SimpleNamespace(affinity_footer=lambda _user: text)


def test_sin_cambio_muestra_el_total():
    assert affinity_footer_for_change(_ctx(), USER, 0) == BASE


def test_subida_muestra_el_delta_explicito():
    assert affinity_footer_for_change(_ctx(), USER, 1) == f"{BASE} (+1)"


def test_bajada_muestra_el_delta_negativo():
    assert affinity_footer_for_change(_ctx(), USER, -2) == f"{BASE} (-2)"


def test_sin_usuario_no_hay_pie():
    assert affinity_footer_for_change(_ctx(), None, 1) == ""


def test_sin_texto_base_no_hay_pie():
    assert affinity_footer_for_change(_ctx(""), USER, 1) == ""
