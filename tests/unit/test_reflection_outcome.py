"""Resultado real de la reflexión introspectiva y su aviso (`!descubrir`)."""

import asyncio

from airi.discord_bot.commands.identity import reflection_notice
from airi.services.self_service import ReflectionOutcome, SelfService
from airi.testing import FakeLLM, llm_json, make_state

NOW = 1_000_000.0

IDENTITY_UPDATE = {
    "key": "traits.curiosa",
    "op": "inc",
    "value": "1",
    "reason": "me lo he replanteado en la pausa",
    "evidence": "he releído mi diario",
}


def run(coro):
    return asyncio.run(coro)


def make_service(llm, state):
    return SelfService(llm=llm, state=state, clock=lambda: NOW)


# ---------------------------------------------------------------------------
# SelfService.reflect → ReflectionOutcome
# ---------------------------------------------------------------------------


def test_reflect_reports_discovery_and_identity_change():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json(
        "ok",
        discovery="Me doy cuenta de que los domingos me gusta cocinar",
        self_update=IDENTITY_UPDATE,
    )])
    svc = make_service(llm, state)

    outcome = run(svc.reflect(42, now=NOW, force=True))

    assert outcome.ran is True
    assert outcome.changed is True
    assert "cocinar" in outcome.discovery
    assert outcome.self_entry["key"] == "traits.curiosa"
    assert any(
        e["text"] == outcome.discovery
        for e in state.self_model()["discoveries"]
    )


def test_reflect_without_changes_runs_but_reports_no_change():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("nada nuevo por ahora")])
    svc = make_service(llm, state)

    outcome = run(svc.reflect(42, now=NOW, force=True))

    assert outcome.ran is True
    assert outcome.changed is False
    assert outcome.discovery is None
    assert outcome.self_entry is None


def test_reflect_skipped_when_not_due():
    state, _ = make_state()
    svc = make_service(FakeLLM(), state)

    # Sin `force` y con 0 interacciones: no toca reflexión.
    outcome = run(svc.reflect(42, now=NOW))

    assert outcome.ran is False
    assert outcome.changed is False


# ---------------------------------------------------------------------------
# reflection_notice: el texto real que ve el canal
# ---------------------------------------------------------------------------


def test_notice_shows_discovery_change_and_command():
    outcome = ReflectionOutcome(
        ran=True,
        discovery="Me doy cuenta de que me gustan las mañanas",
        self_entry={
            "key": "traits.curiosa", "op": "inc", "from": 3, "to": 4,
            "reason": "porque sí", "ts": NOW, "user_id": "42",
            "source": "reflection",
        },
    )

    text = reflection_notice(outcome)

    assert "Descubrimiento" in text
    assert "traits.curiosa" in text
    assert "!identidad-airi" in text


def test_notice_without_changes_says_so():
    text = reflection_notice(ReflectionOutcome(ran=True))

    assert "no he cambiado nada" in text


def test_notice_when_reflection_did_not_run():
    assert "Prueba más tarde" in reflection_notice(ReflectionOutcome())


def test_notice_on_service_error():
    assert "no he conseguido" in reflection_notice(None)
