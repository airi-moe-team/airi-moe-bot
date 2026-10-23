"""Tests unitarios del modo espectador (escucha pasiva + activación local)."""

import re

from airi.domain.spectator import (
    AiriSpectatorPolicy,
    affinity_eligible,
    build_topic_matcher,
    decide_activation,
    load_policy,
    mention_signals,
    positive_taste_terms,
    topic_eligible,
)


def _policy(**overrides):
    base = {
        "enabled": True,
        "affinity_threshold": 20,
        "probability_topic": 0.55,
        "probability_affinity": 0.35,
        "cooldown_seconds": 300,
        "snapshot_max_messages": 12,
        "buffer_max": 20,
        "ttl_seconds": 1800,
        "handoff_seconds": 180,
    }
    base.update(overrides)
    return AiriSpectatorPolicy(**base)


# ------------------------------------------------------------------
# Constantes configurables
# ------------------------------------------------------------------


def test_constants_existen_con_valores_por_defecto(monkeypatch):
    for name in (
        "AIRI_SPECTATOR_ENABLED",
        "AIRI_SPECTATOR_BUFFER_MAX",
        "AIRI_SPECTATOR_TTL_SECONDS",
        "AIRI_SPECTATOR_AFFINITY_POINTS",
        "AIRI_SPECTATOR_PROB_TOPIC",
        "AIRI_SPECTATOR_PROB_AFFINITY",
        "AIRI_SPECTATOR_COOLDOWN_SECONDS",
        "AIRI_SPECTATOR_SNAPSHOT_MAX",
    ):
        monkeypatch.delenv(name, raising=False)
    importlib_probe = __import__("airi.domain.constants", fromlist=["object"])
    constants = importlib_probe
    assert constants.AIRI_SPECTATOR_ENABLED is False
    assert constants.AIRI_SPECTATOR_BUFFER_MAX == 20
    assert constants.AIRI_SPECTATOR_TTL_SECONDS == 1800
    assert constants.AIRI_SPECTATOR_AFFINITY_POINTS == 20
    assert constants.AIRI_SPECTATOR_PROB_TOPIC == 0.55
    assert constants.AIRI_SPECTATOR_PROB_AFFINITY == 0.35
    assert constants.AIRI_SPECTATOR_COOLDOWN_SECONDS == 300
    assert constants.AIRI_SPECTATOR_SNAPSHOT_MAX == 12


def test_load_policy_lee_env(monkeypatch):
    monkeypatch.setenv("AIRI_SPECTATOR_ENABLED", "1")
    monkeypatch.setenv("AIRI_SPECTATOR_AFFINITY_POINTS", "33")
    monkeypatch.setenv("AIRI_SPECTATOR_PROB_TOPIC", "0.2")
    monkeypatch.setenv("AIRI_SPECTATOR_COOLDOWN_SECONDS", "45")
    policy = load_policy()
    assert policy.enabled is True
    assert policy.affinity_threshold == 33
    assert policy.probability_topic == 0.2
    assert policy.cooldown_seconds == 45


# ------------------------------------------------------------------
# Matched de temas sobre el perfil de gustos
# ------------------------------------------------------------------


def test_positive_taste_terms_ignora_dislikes():
    profile = {
        "tastes": {
            "loves": ["videojuegos", "ramen"],
            "dislikes": ["grosero"],
            "favorite_food": "postres y dulces",
            "favorite_flower": "rosas",
        }
    }
    terms = positive_taste_terms(profile)
    lowered = {t.casefold() for t in terms}
    assert "videojuegos" in lowered
    assert "ramen" in lowered
    assert "postres" in lowered
    assert "dulces" in lowered
    assert "rosas" in lowered
    assert "grosero" not in lowered


def test_positive_taste_terms_acepta_preferencias_legacy():
    terms = positive_taste_terms({"loves": ["lol"], "favorite_food": "postres"})
    lowered = {t.casefold() for t in terms}
    assert "lol" in lowered
    assert "postres" in lowered


def test_build_topic_matcher_none_sin_datos():
    assert build_topic_matcher([]) is None


def test_build_topic_matcher_detecta_con_límites_de_palabra():
    pattern = build_topic_matcher(["ramen", "postres y dulces"])
    assert isinstance(pattern, re.Pattern)
    assert topic_eligible(pattern, "¿Alguien tiene ganas de RAMEN?")
    assert topic_eligible(pattern, "me apetecen postres")
    assert not topic_eligible(pattern, "cuento de raymundo")
    assert not topic_eligible(None, "ramen")


def test_topic_eligible_no_coincide_sin_frontera():
    pattern = build_topic_matcher(["ramen"])
    assert not topic_eligible(pattern, "el rameniro cantó")
    assert topic_eligible(pattern, "el ramen está listo")


# ------------------------------------------------------------------
# Señales de mención y afinidad
# ------------------------------------------------------------------


def test_mention_signals_posee_mencion_directa():
    assert mention_signals("hola <@!2026>", "2026", "airi", False)
    assert mention_signals("hola <@2026>", "2026", "airi", False)


def test_mention_signals_con_respuesta():
    assert mention_signals("gracias por todo", "2026", "airi", True)


def test_mention_signals_con_nombre_exacto():
    assert mention_signals("¿airi, me oyes?", "2026", "airi", False)
    assert mention_signals("AIRI", "2026", "airi", False)


def test_mention_signals_rechaza_ruido():
    assert not mention_signals("el sairi llegó", "2026", "airi", False)
    assert not mention_signals("chiari musume", "2026", "airi", False)
    assert not mention_signals("", "2026", "airi", False)


def test_affinity_eligible_respeta_umbral():
    assert affinity_eligible(20, 20)
    assert affinity_eligible(45, 20)
    assert not affinity_eligible(19, 20)


# ------------------------------------------------------------------
# Decisión de activación
# ------------------------------------------------------------------


def test_mencion_garantizada_aunque_la_tirada_falle():
    decision = decide_activation(
        mention=True, topic=False, affinity=False, roll=0.99, policy=_policy()
    )
    assert decision.proceed
    assert decision.guaranteed
    assert decision.reason == "mention"


def test_temas_dependen_de_la_tirada():
    ok = decide_activation(
        mention=False, topic=True, affinity=False, roll=0.5, policy=_policy()
    )
    silenciada = decide_activation(
        mention=False, topic=True, affinity=False, roll=0.8, policy=_policy()
    )
    assert ok.proceed
    assert ok.guaranteed is False
    assert ok.reason == "topic"
    assert not silenciada.proceed
    assert not silenciada.guaranteed
    assert silenciada.reason == "topic"


def test_afinidad_depende_de_la_tirada():
    ok = decide_activation(
        mention=False, topic=False, affinity=True, roll=0.3, policy=_policy()
    )
    silenciada = decide_activation(
        mention=False, topic=False, affinity=True, roll=0.6, policy=_policy()
    )
    assert ok.proceed and ok.reason == "affinity"
    assert not silenciada.proceed
    assert silenciada.reason == "affinity"


def test_senales_combinadas_usan_la_probabilidad_mayor():
    ajena = _policy(probability_topic=0.9, probability_affinity=0.2)
    decision = decide_activation(
        mention=False, topic=True, affinity=True, roll=0.95, policy=ajena
    )
    assert not decision.proceed
    # 0.95 no supera la mayor (0.9), por lo que no procede; con 0.85 sí.
    decision_ok = decide_activation(
        mention=False, topic=True, affinity=True, roll=0.85, policy=ajena
    )
    assert decision_ok.proceed


def test_modo_desactivado_no_procede():
    off = _policy(enabled=False)
    decision = decide_activation(
        mention=True, handoff=False, topic=True, affinity=True, roll=0.0, policy=off
    )
    assert not decision.proceed
    assert decision.reason is None


def test_sin_senal_no_procede():
    decision = decide_activation(
        mention=False, handoff=False, topic=False, affinity=False, roll=0.0,
        policy=_policy(),
    )
    assert not decision.proceed
    assert decision.reason is None


def test_handoff_garantizado_antes_de_otras_senales():
    decision = decide_activation(
        mention=False, handoff=True, topic=True, affinity=True, roll=0.99,
        policy=_policy(),
    )
    assert decision.proceed
    assert decision.reason == "handoff"
    assert decision.guaranteed


# ------------------------------------------------------------------
# Buffer pasivo por canal
# ------------------------------------------------------------------


def _buffer(**kw):
    from airi.services.passive_buffer import PassiveBuffer

    return PassiveBuffer(**kw)


def test_buffer_fifo_respeta_limite():
    buf = _buffer(buffer_max=3, ttl_seconds=1000, clock=lambda: 100.0)
    for i in range(5):
        buf.append(f"c{__import__('uuid').uuid4()}" if False else "c1", f"u{i}", f"U{i}", f"msg{i}")
    channel = next(iter(buf._channels))
    snapshot = buf.snapshot(channel, now=100.0)
    assert len(snapshot) == 3
    assert [e.content for e in snapshot] == ["msg2", "msg3", "msg4"]


def test_buffer_descarta_por_ttl():
    now = [1000.0]

    def clock():
        return now[0]

    buf = _buffer(buffer_max=10, ttl_seconds=100, clock=clock)
    buf.append("c", "u1", "U1", "antiguo")
    now[0] = 1101.0
    buf.append("c", "u2", "U2", "reciente")
    snapshot = buf.snapshot("c", now=1101.0)
    assert [e.content for e in snapshot] == ["reciente"]


def test_buffer_snapshot_excluye_ids_trigger():
    buf = _buffer(buffer_max=10, ttl_seconds=1000, clock=lambda: 5.0)
    buf.append("c", "u1", "U1", " context ", message_id="m1")
    buf.append("c", "u2", "U2", "otro", message_id="m2")
    snapshot = buf.snapshot("c", now=5.0, exclude_ids={"m2"})
    assert [e.message_id for e in snapshot] == ["m1"]


def test_buffer_snapshot_limpia_el_contenido():
    buf = _buffer(buffer_max=10, ttl_seconds=1000, clock=lambda: 5.0)
    buf.append("c", "u1", "U1", "  hola   mundo  ")
    snapshot = buf.snapshot("c", now=5.0)
    assert snapshot[0].content == "hola mundo"


def test_buffer_mark_consumed_retira_los_incluidos():
    buf = _buffer(buffer_max=10, ttl_seconds=1000, clock=lambda: 5.0)
    buf.append("c", "u1", "U1", "a", message_id="m1")
    buf.append("c", "u2", "U2", "b", message_id="m2")
    buf.mark_consumed("c", {"m1"})
    snapshot = buf.snapshot("c", now=5.0)
    assert [e.message_id for e in snapshot] == ["m2"]


def test_buffer_clear():
    buf = _buffer(buffer_max=10, ttl_seconds=1000, clock=lambda: 5.0)
    buf.append("c", "u1", "U1", "a", message_id="m1")
    buf.clear("c")
    assert buf.snapshot("c", now=5.0) == []
