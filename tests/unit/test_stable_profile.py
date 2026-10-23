"""Perfil canónico de gustos configurable por entorno + self-updates sin gustos."""


from airi.domain.spectator import load_stable_profile
from airi.services.state import AppState


def test_load_stable_profile_sin_variable(monkeypatch):
    monkeypatch.delenv("AIRI_PROFILE", raising=False)
    assert load_stable_profile() is None


def test_load_stable_profile_json_valido(monkeypatch):
    monkeypatch.setenv(
        "AIRI_PROFILE",
        '{"loves":["videojuegos","ramen"],"dislikes":["grosero"],'
        '"favorite_food":"ramen y dulces","favorite_flower":"las rosas"}',
    )
    profile = load_stable_profile()
    assert profile == {
        "loves": ["videojuegos", "ramen"],
        "dislikes": ["grosero"],
        "favorite_food": "ramen y dulces",
        "favorite_flower": "las rosas",
    }


def test_load_stable_profile_json_invalido(monkeypatch):
    monkeypatch.setenv("AIRI_PROFILE", "{no-es-json")
    assert load_stable_profile() is None


def test_load_stable_profile_componentes_raros_se_ignoran(monkeypatch):
    monkeypatch.setenv(
        "AIRI_PROFILE",
        '{"loves":["videojuegos",123,["anidado"]],'
        '"favorite_food":"  postres  ","favorite_flower":""}',
    )
    profile = load_stable_profile()
    assert profile["loves"] == ["videojuegos"]
    assert profile["favorite_food"] == "postres"
    assert profile["favorite_flower"] == ""


def test_apply_stable_profile_persiste_en_preferences():
    from airi.services.passive_buffer import apply_stable_profile

    state = AppState()
    state.world.pop("preferences", None)
    profile = {"loves": ["ramen"], "dislikes": [], "favorite_food": "ramen",
               "favorite_flower": "rosas"}
    saved = apply_stable_profile(state, profile)
    assert saved is True
    assert state.world["preferences"]["loves"] == ["ramen"]


def test_apply_stable_profile_none_no_toca_estado():
    from airi.services.passive_buffer import apply_stable_profile

    state = AppState()
    before = dict(state.world.get("preferences", {}))
    assert apply_stable_profile(state, None) is False
    assert dict(state.world.get("preferences", {})) == before


def test_self_update_ya_no_modifica_gustos():
    from airi.domain.self_model import apply_self_update

    state = AppState()
    model = state.self_model()
    before = {
        "loves": list(model["tastes"]["loves"]),
        "favorite_food": model["tastes"]["favorite_food"],
    }
    entry = apply_self_update(
        model,
        {"key": "tastes.loves", "op": "add", "value": "ramen",
         "reason": "prueba", "evidence": "prueba"},
        now=1_000_000.0,
        user_id="42",
        source="message",
    )
    assert entry is None
    assert list(model["tastes"]["loves"]) == before["loves"]
    assert model["tastes"]["favorite_food"] == before["favorite_food"]


def test_self_update_de_personalidad_sigue_funcionando():
    from airi.domain.self_model import SELF_TRAITS_ALLOWLIST, apply_self_update

    state = AppState()
    model = state.self_model()
    key = next(iter(SELF_TRAITS_ALLOWLIST))
    before = int(model["traits"].get(key, 0))
    entry = apply_self_update(
        model,
        {"key": f"traits.{key}", "op": "inc", "value": "1",
         "reason": "prueba", "evidence": "prueba"},
        now=1_000_000.0,
        user_id="42",
        source="message",
    )
    assert entry is not None
    assert int(model["traits"][key]) == before + 1
