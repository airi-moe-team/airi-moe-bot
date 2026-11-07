import json
import os
import subprocess
import sys

import pytest

from airi.domain.prompts import SCENE_PROPOSAL_PROMPT, build_system_prompt
from airi.persona import character_prompt, load_persona


def test_default_profile_is_compatible(monkeypatch):
    monkeypatch.delenv("AIRI_PERSONA_FILE", raising=False)
    assert load_persona().legacy
    assert "Tu nombre es Airi" in build_system_prompt()


def test_second_character_shares_family_but_not_airi_personal_experiences(monkeypatch):
    monkeypatch.setenv("AIRI_PERSONA_FILE", "config/luna.json")
    prompt = build_system_prompt()
    assert "Tu nombre es Luna" in prompt
    assert "Clara y Mateo" in prompt
    assert "Eres hermana de Airi" in prompt
    assert "Nerea" not in prompt
    assert "Gael" not in prompt
    auxiliary = character_prompt(SCENE_PROPOSAL_PROMPT)
    assert "Luna" in auxiliary
    assert "Eres Airi." not in auxiliary
    assert "Eres hermana de Airi" in auxiliary
    assert "Propón" in auxiliary
    # User content must never be passed through this transformation by the adapter.


def test_invalid_profile_fails_before_startup(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"id": "luna"}))
    with pytest.raises(ValueError):
        load_persona(str(path))


def test_process_profile_preserves_other_character_names_in_dynamic_context():
    code = """
from airi.domain.prompts import build_system_prompt, SCENE_PROPOSAL_PROMPT
prompt = build_system_prompt(sections=['Public participant: Airi; user said "Airi".'])
assert 'Tu nombre es Luna' in prompt
assert 'Clara y Mateo' in prompt
assert 'Eres hermana de Airi' in prompt
assert 'Public participant: Airi; user said "Airi".' in prompt
assert 'Luna' in SCENE_PROPOSAL_PROMPT
assert 'Eres Airi' not in SCENE_PROPOSAL_PROMPT
from airi.domain.texts import gift_reaction
from airi.discord_bot.embeds import HELP_TEXT
reaction = gift_reaction('Airi', 1)
assert '*Luna' in reaction
assert 'Airi' in reaction  # interpolated gift/user content is preserved
assert 'Conocer a Luna' in HELP_TEXT
"""
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        env={**os.environ, "AIRI_PERSONA_FILE": "config/luna.json", "PYTHONPATH": "src"},
    )
