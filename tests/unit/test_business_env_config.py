"""Configuración de negocio cargada desde el entorno."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
CONFIG_KEYS = (
    "AFFINITY_LEVELS",
    "DATE_SCENES",
    "SELF_TRAITS_ALLOWLIST",
    "SELF_BASE_TRAITS",
    "SELF_TRAIT_MIN",
    "SELF_TRAIT_MAX",
    "SELF_KEY_DAILY_LIMIT",
    "SELF_HISTORY_MAX",
    "DATE_MAX_SECONDS",
)


def _run_python(code, overrides=None):
    env = os.environ.copy()
    for key in CONFIG_KEYS:
        env.pop(key, None)
    env.update(overrides or {})
    source_path = str(ROOT / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (source_path, env.get("PYTHONPATH")))
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _load_config(overrides=None):
    code = """
import json
from airi.domain.affinity import can_date
from airi.domain.constants import (
    AFFINITY_LEVELS,
    DATE_SCENES,
    SELF_KEY_DAILY_LIMIT,
    SELF_BASE_TRAITS,
    SELF_TRAITS_ALLOWLIST,
)
from airi.domain.self_model import default_self, is_mutable_key
seeded = default_self()
print(json.dumps({
    "levels": AFFINITY_LEVELS,
    "scenes": DATE_SCENES,
    "trait_names": SELF_TRAITS_ALLOWLIST,
    "trait_values": SELF_BASE_TRAITS,
    "daily_limit": SELF_KEY_DAILY_LIMIT,
    "seeded_traits": seeded["traits"],
    "allows_custom_trait": is_mutable_key("traits.serena"),
    "date_before_threshold": can_date(AFFINITY_LEVELS[6][0] - 1),
    "date_at_threshold": can_date(AFFINITY_LEVELS[6][0]),
}, ensure_ascii=False))
"""
    result = _run_python(code, overrides)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), result.stderr


def test_business_settings_keep_current_defaults_when_environment_is_empty():
    config, stderr = _load_config()

    assert config["levels"][6] == [25, "Amiga"]
    assert config["scenes"][0] == "un paseo por el parque al atardecer"
    assert config["trait_names"] == [
        "expresiva", "timida", "juguetona", "celosa", "sarcastica", "curiosa"
    ]
    assert config["trait_values"]["curiosa"] == 4
    assert config["seeded_traits"] == config["trait_values"]
    assert config["allows_custom_trait"] is False
    assert config["date_before_threshold"] is False
    assert config["date_at_threshold"] is True
    assert stderr == ""


def test_business_settings_are_loaded_from_json_environment_values():
    levels = [[-60, "Nivel 1"], [-50, "Nivel 2"], [-40, "Nivel 3"],
              [-30, "Nivel 4"], [-20, "Nivel 5"], [-10, "Nivel 6"],
              [50, "Compañera"]]
    config, stderr = _load_config({
        "AFFINITY_LEVELS": json.dumps(levels, ensure_ascii=False),
        "DATE_SCENES": json.dumps(["Un jardín", "Un museo"], ensure_ascii=False),
        "SELF_TRAITS_ALLOWLIST": json.dumps(["curiosa", "serena"]),
        "SELF_BASE_TRAITS": json.dumps({"curiosa": 2, "serena": 3}),
    })

    assert config["levels"] == levels
    assert config["scenes"] == ["Un jardín", "Un museo"]
    assert config["trait_names"] == ["curiosa", "serena"]
    assert config["trait_values"] == {"curiosa": 2, "serena": 3}
    assert config["seeded_traits"] == config["trait_values"]
    assert config["allows_custom_trait"] is True
    assert config["date_before_threshold"] is False
    assert config["date_at_threshold"] is True
    assert stderr == ""


def test_invalid_business_settings_fall_back_with_warnings():
    config, stderr = _load_config({
        "AFFINITY_LEVELS": "[[0, 'not-json']]",
        "DATE_SCENES": "[]",
        "SELF_TRAITS_ALLOWLIST": '["curiosa"]',
        "SELF_BASE_TRAITS": '{"serena": 3}',
    })

    assert config["levels"][6] == [25, "Amiga"]
    assert config["scenes"][0] == "un paseo por el parque al atardecer"
    assert config["trait_names"][-1] == "curiosa"
    assert config["trait_values"]["curiosa"] == 4
    assert "AFFINITY_LEVELS" in stderr
    assert "DATE_SCENES" in stderr
    assert "SELF_TRAITS_ALLOWLIST" in stderr
    assert "not-json" not in stderr


@pytest.mark.parametrize(
    "levels",
    [
        [[0, "A"], [0, "B"], [1, "C"], [2, "D"], [3, "E"], [4, "F"], [5, "G"]],
        [[0, "A"], [1, "A"], [2, "C"], [3, "D"], [4, "E"], [5, "F"], [6, "G"]],
        [[0, "A"], [1, " "], [2, "C"], [3, "D"], [4, "E"], [5, "F"], [6, "G"]],
        [[0, "A"], [1, "B"], [2, "C"]],
    ],
)
def test_invalid_affinity_level_invariants_fall_back(levels):
    config, stderr = _load_config({"AFFINITY_LEVELS": json.dumps(levels)})

    assert config["levels"][6] == [25, "Amiga"]
    assert "AFFINITY_LEVELS" in stderr


@pytest.mark.parametrize("scenes", [[], [""], ["museo", "museo"], {"scene": "museo"}])
def test_invalid_date_scene_shapes_fall_back(scenes):
    config, stderr = _load_config({"DATE_SCENES": json.dumps(scenes)})

    assert config["scenes"][0] == "un paseo por el parque al atardecer"
    assert "DATE_SCENES" in stderr


def test_out_of_range_base_trait_falls_back_as_a_pair():
    config, stderr = _load_config({
        "SELF_TRAITS_ALLOWLIST": '["curiosa"]',
        "SELF_BASE_TRAITS": '{"curiosa": 6}',
    })

    assert config["trait_names"][-1] == "curiosa"
    assert len(config["trait_names"]) == 6
    assert "SELF_TRAITS_ALLOWLIST/SELF_BASE_TRAITS" in stderr


@pytest.mark.parametrize("limit", ["0", "-1", "201"])
def test_invalid_daily_update_limit_falls_back(limit):
    config, stderr = _load_config({"SELF_KEY_DAILY_LIMIT": limit})

    assert config["daily_limit"] == 1
    assert "SELF_KEY_DAILY_LIMIT" in stderr


def test_valid_daily_update_limit_is_loaded():
    config, stderr = _load_config({"SELF_KEY_DAILY_LIMIT": "2"})

    assert config["daily_limit"] == 2
    assert stderr == ""


def test_example_environment_documents_valid_business_json():
    values = dotenv_values(ROOT / ".env.example")

    levels = json.loads(values["AFFINITY_LEVELS"])
    scenes = json.loads(values["DATE_SCENES"])
    allowlist = json.loads(values["SELF_TRAITS_ALLOWLIST"])
    base_traits = json.loads(values["SELF_BASE_TRAITS"])

    assert len(levels) >= 7
    assert scenes
    assert set(allowlist) == set(base_traits)
    assert values["SELF_KEY_DAILY_LIMIT"] == "1"


def test_main_module_loads_dotenv_before_importing_bot_modules():
    code = r"""
import builtins
import os
import sys
import types
import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: os.environ.__setitem__("DOTENV_READY", "1")
import airi.__main__ as entrypoint

assert "airi.domain.constants" not in sys.modules
assert "airi.observability.replay" not in sys.modules
assert os.getenv("DOTENV_READY") == "1"

client = types.ModuleType("airi.discord_bot.client")
client.run_bot = lambda argv: 23
original_import = builtins.__import__

def tracked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "airi.discord_bot.client":
        assert os.getenv("DOTENV_READY") == "1"
        return client
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = tracked_import
try:
    assert entrypoint.cmd_run([]) == 23
finally:
    builtins.__import__ = original_import
"""
    result = _run_python(code)

    assert result.returncode == 0, result.stderr
