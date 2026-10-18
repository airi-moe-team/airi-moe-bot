"""Registro de comandos: `!identidad-airi` con alias `!yo` y sus subcomandos."""

from airi.discord_bot.commands import build_registry
from airi.discord_bot.commands import identity

REG = build_registry()


def _raw(content):
    """Handler subyacente (desenvuelve el decorador `traced`)."""
    handler = REG.match(content)
    return None if handler is None else getattr(handler, "__wrapped__", handler)


def test_identidad_airi_exact_resuelve_a_handle_yo():
    assert _raw("!identidad-airi") is identity.handle_yo


def test_alias_yo_sigue_funcionando():
    assert _raw("!yo") is identity.handle_yo


def test_subcomando_historia_con_ambos_nombres():
    assert _raw("!identidad-airi historia") is identity.handle_yo_historia
    assert _raw("!yo historia") is identity.handle_yo_historia


def test_subcomando_revertir_con_ambos_nombres():
    assert _raw("!identidad-airi revertir 3") is identity.handle_yo_revertir
    assert _raw("!yo revertir 3") is identity.handle_yo_revertir


def test_subcomandos_con_arguments_extienden_el_prefijo():
    assert _raw("!identidad-airi historia extra") is identity.handle_yo_historia


def test_texto_que_no_es_comando_no_matchea():
    assert REG.match("!identidad-airi qué") is None
    assert REG.match("!yolo") is None
