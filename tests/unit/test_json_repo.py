"""Tests del repositorio JSON: cargas robustas y guardado atómico (2.2)."""

import json

from airi.adapters.json_repo import load_json, load_json_list, save_json


def test_save_json_is_readable_and_atomic(tmp_path):
    path = tmp_path / "data.json"
    save_json(str(path), {"a": 1, "texto": "ñ"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1, "texto": "ñ"}
    # El temporal se limpió (se renombró encima del destino).
    assert not (tmp_path / "data.json.tmp").exists()


def test_load_json_missing_returns_default(tmp_path):
    default = {"x": 0}
    assert load_json(str(tmp_path / "nope.json"), default) is default


def test_load_json_corrupt_returns_default(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ esto no es json", encoding="utf-8")

    assert load_json(str(path), {}) == {}


def test_load_json_ignores_non_object(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert load_json(str(path), {"default": True}) == {"default": True}


def test_load_json_list(tmp_path):
    path = tmp_path / "diary.json"
    save_json(str(path), [{"kind": "date"}])

    assert load_json_list(str(path)) == [{"kind": "date"}]
    assert load_json_list(str(tmp_path / "missing.json")) == []
    assert load_json_list(str(tmp_path / "missing.json"), ["x"]) == ["x"]


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "world.json"
    data = {"season": 2, "characters": {"airi": True}}
    save_json(str(path), data)

    assert load_json(str(path), {}) == data
