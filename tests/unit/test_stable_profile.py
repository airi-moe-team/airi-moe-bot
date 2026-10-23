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


def test_sync_preferences_from_self_queda_como_no_op():
    """El fast-sync legacy NO puede pisar el perfil canónico de gustos."""
    from airi.domain.self_model import sync_preferences_from_self

    world = {
        "self": {"tastes": {"loves": ["otra cosa"], "dislikes": [],
                            "favorite_food": "otra", "favorite_flower": "x"}},
        "preferences": {"loves": ["ramen"], "dislikes": [],
                        "favorite_food": "dulces", "favorite_flower": "tulipanes"},
    }
    sync_preferences_from_self(world)
    assert world["preferences"] == {
        "loves": ["ramen"], "dislikes": [],
        "favorite_food": "dulces", "favorite_flower": "tulipanes",
    }


def test_apply_turn_no_resincroniza_gustos_tras_personalidad():
    from airi.domain.self_model import SELF_TRAITS_ALLOWLIST, apply_self_update

    state = AppState()
    canonical = {
        "loves": ["ramen"],
        "dislikes": ["grosero"],
        "favorite_food": "dulces",
        "favorite_flower": "tulipanes",
    }
    state.world["preferences"] = dict(canonical)
    key = next(iter(SELF_TRAITS_ALLOWLIST))
    entry = apply_self_update(
        state.self_model(),
        {"key": f"traits.{key}", "op": "inc", "value": "1",
         "reason": "prueba", "evidence": "prueba"},
        now=1_000_000.0,
        user_id="42",
        source="message",
    )
    assert entry is not None
    assert state.world["preferences"] == dict(canonical)


def test_load_policy_lee_handoff_seconds(monkeypatch):
    from airi.domain.spectator import load_policy

    monkeypatch.setenv("AIRI_SPECTATOR_HANDOFF_SECONDS", "99")
    policy = load_policy()
    assert policy.handoff_seconds == 99


def test_decide_activation_handoff_es_garantizado():
    from airi.domain import spectator
    from tests.unit.test_spectator import _policy

    decision = spectator.decide_activation(
        mention=False, handoff=True, topic=False, affinity=False,
        roll=0.99, policy=_policy(),
    )
    assert decision.proceed
    assert decision.guaranteed and decision.reason == "handoff"


def test_decide_activation_sin_handoff_intacta():
    from airi.domain import spectator
    from tests.unit.test_spectator import _policy

    decision = spectator.decide_activation(
        mention=False, handoff=False, topic=True, affinity=False,
        roll=0.1, policy=_policy(),
    )
    assert decision.proceed and decision.reason == "topic"


def test_evaluate_event_handoff_bypassa_cooldown():
    from airi.services.spectator_policy import ActivitiesCooldown, evaluate_event
    from tests.unit.test_spectator import _policy

    gate = ActivitiesCooldown(cooldown_seconds=300, clock=lambda: 1000.0)
    gate.arm("7", "99", now=1000.0)
    decision = evaluate_event(
        policy=_policy(), gate=gate, channel_id="7", author_id="99",
        mention=False, handoff=True, topic=False, affinity=False,
    )
    assert decision.proceed and decision.reason == "handoff"


def test_gate_handoff_expira_clear_y_una_sola_vez():
    from airi.services.spectator_policy import ActivitiesCooldown

    gate = ActivitiesCooldown(cooldown_seconds=300, clock=lambda: 1000.0)
    assert not gate.has_pending_handoff("7", "99", now=1000.0)
    gate.arm_handoff("7", "99", now=1000.0)
    assert gate.has_pending_handoff("7", "99", now=999.0)
    # Fuera de la ventana expira solo.
    assert not gate.has_pending_handoff("7", "99", now=1000.0 + 240)
    gate.arm_handoff("7", "99", now=1000.0)
    gate.clear_handoff("7", "99")
    assert not gate.has_pending_handoff("7", "99", now=1001.0)
