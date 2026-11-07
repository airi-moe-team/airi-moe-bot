import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from airi.persona import load_persona


def test_sisters_share_canon_with_independent_perspectives():
    airi = load_persona("config/airi.json")
    luna = load_persona("config/luna.json")
    assert airi.family == luna.family
    assert airi.family.parents == ("Clara", "Mateo")
    assert airi.sibling_perspective != luna.sibling_perspective
    assert "Eres hermana de Luna" in airi.family_prompt()
    assert "Eres hermana de Airi" in luna.family_prompt()
    assert "Nerea" in airi.biography
    assert "Nerea" not in luna.biography
    assert "No se han definido edades" in airi.family_prompt()
    assert "conversaciones privadas" in luna.family_prompt()
    for persona in (airi, luna):
        assert "Airi es la hermana mayor y Luna es la hermana menor" in persona.family_prompt()
        assert "ni quién es la hermana mayor" not in persona.family_prompt()
    assert "Luna es mi hermana menor" in airi.sibling_perspective
    assert "Airi es mi hermana mayor" in luna.sibling_perspective


@pytest.mark.parametrize("character,sister", [("airi", "Luna"), ("luna", "Airi")])
def test_actual_process_prompts_include_one_shared_canon(character, sister):
    code = """
import os
from airi.persona import current_persona
from airi.domain.prompts import build_system_prompt, SYSTEM_PROMPT, SCENE_PROPOSAL_PROMPT
persona = current_persona()
for prompt in (build_system_prompt(), build_system_prompt(compact=True), SYSTEM_PROMPT, SCENE_PROPOSAL_PROMPT):
    assert "Eres hermana de " + os.environ["TEST_SISTER"] in prompt
    assert "Clara y Mateo" in prompt
    assert "hija única" not in prompt
    assert "Airi es la hermana mayor y Luna es la hermana menor" in prompt
    assert prompt.count("=== HISTORIA FAMILIAR COMPARTIDA") == 1
    for memory in persona.family.memories:
        assert memory in prompt
if persona.id == "airi":
    assert "Nerea" in SYSTEM_PROMPT
    assert "Gael" in SYSTEM_PROMPT
else:
    assert "Nerea" not in SYSTEM_PROMPT
    assert "Gael" not in SYSTEM_PROMPT
"""
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        env={
            **os.environ,
            "AIRI_PERSONA_FILE": f"config/{character}.json",
            "TEST_SISTER": sister,
            "PYTHONPATH": "src",
        },
    )


def test_relative_family_file_does_not_depend_on_working_directory(tmp_path, monkeypatch):
    profile = Path("config/luna.json").resolve()
    monkeypatch.chdir(tmp_path)
    luna = load_persona(str(profile))
    assert luna.family.parents == ("Clara", "Mateo")


@pytest.mark.parametrize("character", ["airi", "luna"])
def test_family_file_is_the_source_of_shared_facts(tmp_path, character):
    profile = json.loads(Path(f"config/{character}.json").read_text())
    family = json.loads(Path("config/family.json").read_text())
    family["parents"] = ["Elena", "Daniel"]
    (tmp_path / "family.json").write_text(json.dumps(family))
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile))
    code = '''
from airi.domain.prompts import build_system_prompt, SYSTEM_PROMPT
for prompt in (build_system_prompt(), SYSTEM_PROMPT):
    assert "Elena y Daniel" in prompt
    assert "Clara y Mateo" not in prompt
'''
    subprocess.run([sys.executable, "-c", code], check=True, env={
        **os.environ, "AIRI_PERSONA_FILE": str(profile_path), "PYTHONPATH": "src",
    })


@pytest.mark.parametrize(
    "invalid", ["unknown_member", "missing_perspective", "duplicate_members", "missing_file"]
)
def test_invalid_family_configuration_fails_at_load(tmp_path, invalid):
    profile = json.loads(Path("config/luna.json").read_text())
    family = json.loads(Path("config/family.json").read_text())
    if invalid == "unknown_member":
        profile["id"] = "someone_else"
    elif invalid == "missing_perspective":
        profile.pop("sibling_perspective")
    elif invalid == "duplicate_members":
        family["members"][1] = family["members"][0]
    elif invalid == "missing_file":
        profile["family_file"] = "missing.json"
    (tmp_path / "family.json").write_text(json.dumps(family))
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile))
    with pytest.raises((ValueError, FileNotFoundError)):
        load_persona(str(path))
