from types import SimpleNamespace

import pytest

from airi.discord_bot.commands import build_registry
from airi.discord_bot.commands.identity import reflection_notice


@pytest.mark.parametrize("character,other", [("airi", "luna"), ("luna", "airi")])
def test_registry_only_accepts_own_character_aliases(monkeypatch, character, other):
    monkeypatch.setenv("AIRI_PERSONA_FILE", f"config/{character}.json")
    registry = build_registry()
    assert registry.match(f"!identidad-{character}") is registry.match("!yo")
    assert registry.match(f"!animo-{character}") is registry.match("!animo")
    assert registry.match("!yo") is not None
    assert registry.match("!animo") is not None
    for subcommand in ("historia", "revertir 1"):
        assert registry.match(f"!identidad-{character} {subcommand}") is registry.match(
            f"!yo {subcommand}"
        )
        assert registry.match(f"!identidad-{character} {subcommand}") is not None
        assert registry.match(f"!identidad-{other} {subcommand}") is None
    assert registry.match(f"!identidad-{other}") is None
    assert registry.match(f"!animo-{other}") is None
    assert registry.match(f"!IDENTIDAD-{character.upper()}") is registry.match("!yo")


def test_default_registry_preserves_airi_aliases(monkeypatch):
    monkeypatch.delenv("AIRI_PERSONA_FILE", raising=False)
    registry = build_registry()
    assert registry.match("!identidad-airi") is registry.match("!yo")
    assert registry.match("!animo-airi") is registry.match("!animo")
    assert registry.match("!identidad-luna") is None


@pytest.mark.parametrize("character", ["airi", "luna"])
def test_reflection_points_to_registered_alias(monkeypatch, character):
    monkeypatch.setenv("AIRI_PERSONA_FILE", f"config/{character}.json")
    notice = reflection_notice(
        SimpleNamespace(ran=True, changed=True, discovery=None, self_entry=None)
    )
    assert f"`!identidad-{character}`" in notice
