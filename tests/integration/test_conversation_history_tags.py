"""Integración: la vista de inferencia atribuye identidad y afinidad correctas.

Reproduce el escenario de un canal compartido: Mathias tiene afinidad alta y
KOKODA, negativa. Se comprueba la ATRIBUCIÓN (cada turno lleva su etiqueta),
el ESTADO (la afinidad se aplica al usuario correcto y una sola vez) y que la
vista no contamina el historial canónico.
"""

from __future__ import annotations

import asyncio
import json

from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeLLM, FakeNotifier, FakeUser, llm_json, make_state

NOW = 1_000_000.0

MATHIAS = FakeUser(10, "Mathias")
KOKODA = FakeUser(42, "KOKODA")
DAVID = FakeUser(77, "David")


def run(coro):
    return asyncio.run(coro)


def make_service(llm, state, **kw):
    return ConversationService(
        llm=llm,
        state=state,
        notifier=FakeNotifier(),
        clock=lambda: NOW,
        date_delta_max=5,
        **kw,
    )


def seed_group_state():
    """Mathias tiene afinidad alta; KOKODA, negativa. Historial ya existente."""
    affinity = {
        "10": {"points": 60, "last_gain": 0.0, "last_interaction": NOW, "milestones": []},
        "42": {"points": -16, "last_gain": 0.0, "last_interaction": NOW, "milestones": []},
    }
    history = [
        {"role": "user", "content": "Mathias: hola Airi~",
         "author_id": "10", "author_name": "Mathias"},
        {"role": "assistant",
         "content": llm_json("¡Hola, Mathias! *se sonroja* Qué alegría verte~"),
         "reply_to_user_id": "10", "reply_to_user_name": "Mathias"},
    ]
    state, counters = make_state(affinity=affinity, histories={0: history})
    return state, counters


KOKODA_REPLY = llm_json(
    "¿Que fácil? *cruza los brazos* A ti no te he dado confianza para eso.",
    gif="angry",
    affinity_delta=-2,
    affinity_event="me faltó al respeto",
)


def test_attribution_each_turn_gets_its_own_speaker_tag():
    state, _ = seed_group_state()
    llm = FakeLLM(replies=[KOKODA_REPLY])
    # Alcance "all": cada interlocutor lleva SU afinidad (atribución completa).
    svc = make_service(llm, state, affinity_scope="all")

    run(svc.run_turn(KOKODA, [(KOKODA, "Airi que fácil eres")], TurnContext()))

    sent = llm.calls[-1]["messages"]
    contents = [m["content"] for m in sent if m["role"] != "system"]
    # Mathias conserva SU afinidad alta en su turno...
    assert any("[speaker=Mathias|affinity=60|level=Interés] hola Airi~" in c for c in contents)
    # ...y KOKODA recibe una etiqueta con SU afinidad negativa (no la de Mathias).
    assert any(
        "[speaker=KOKODA|affinity=-16|level=Molesta] Airi que fácil eres" in c
        for c in contents
    )
    # La respuesta anterior de Airi queda anotada con su destinatario real.
    assert any("[reply_to=Mathias]" in c for c in contents)


def test_state_affinity_is_applied_to_the_right_user_once():
    state, counters = seed_group_state()
    llm = FakeLLM(replies=[KOKODA_REPLY])
    svc = make_service(llm, state)

    result = run(svc.run_turn(KOKODA, [(KOKODA, "Airi que fácil eres")], TurnContext()))

    assert state.entry_points(42) == -18  # KOKODA baja su afinidad...
    assert state.entry_points(10) == 60   # ...Mathias no se toca.
    assert result.affinity_applied == -2
    assert counters["affinity"] == 1      # exactamente una actualización.


def test_valid_json_contract_is_returned():
    state, _ = seed_group_state()
    llm = FakeLLM(replies=[KOKODA_REPLY])
    svc = make_service(llm, state)

    result = run(svc.run_turn(KOKODA, [(KOKODA, "Airi que fácil eres")], TurnContext()))

    assert result.reply.startswith("¿Que fácil?")
    assert result.gif == "angry"
    payload = json.loads(state.histories[0][-1]["content"])
    for key in ("reply", "gif", "affinity_delta", "affinity_event", "date_decision"):
        assert key in payload


def test_canonical_history_is_not_contaminated_by_tags():
    state, _ = seed_group_state()
    llm = FakeLLM(replies=[KOKODA_REPLY])
    svc = make_service(llm, state)

    run(svc.run_turn(KOKODA, [(KOKODA, "Airi que fácil eres")], TurnContext()))

    for entry in state.histories[0]:
        assert "[speaker=" not in entry["content"]
        assert "[reply_to=" not in entry["content"]
    # El historial de usuario conserva el texto tal cual...
    user_entries = [e for e in state.histories[0] if e["role"] == "user"]
    assert user_entries[-1]["content"] == "Airi que fácil eres"
    # ...y conserva los metadatos estructurados para futuras inferencias.
    assert user_entries[-1]["author_id"] == "42"
    assert user_entries[-1]["author_name"] == "KOKODA"


def test_api_messages_only_expose_role_and_content():
    state, _ = seed_group_state()
    llm = FakeLLM(replies=[KOKODA_REPLY])
    svc = make_service(llm, state)

    run(svc.run_turn(KOKODA, [(KOKODA, "Airi que fácil eres")], TurnContext()))

    for message in llm.calls[-1]["messages"]:
        assert set(message.keys()) == {"role", "content"}


# ---------------------------------------------------------------------------
# Afinidad desconocida ⇒ neutral (no se inventa un cero)
# ---------------------------------------------------------------------------


def test_unknown_user_is_tagged_unknown_not_zero():
    """Un interlocutor SIN registro de afinidad se marca `unknown`, no 0."""
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "hola", "author_id": "999", "author_name": "Extra"},
    ]
    llm = FakeLLM(replies=[llm_json("hola")])
    svc = make_service(llm, state, affinity_scope="all")

    run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    contents = [m["content"] for m in llm.calls[-1]["messages"][1:]]
    assert any("speaker=Extra|affinity=unknown" in c for c in contents)
    assert not any("speaker=Extra|affinity=0" in c for c in contents)


# ---------------------------------------------------------------------------
# Ámbito de la afinidad expuesta (no filtrar el vínculo con terceros)
# ---------------------------------------------------------------------------


def test_default_scope_hides_third_party_affinity():
    state, _ = seed_group_state()
    llm = FakeLLM(replies=[KOKODA_REPLY])
    svc = make_service(llm, state)  # alcance por defecto: "recipient"

    run(svc.run_turn(KOKODA, [(KOKODA, "Airi que fácil eres")], TurnContext()))

    contents = [m["content"] for m in llm.calls[-1]["messages"][1:]]
    # El destinatario conserva SU afinidad...
    assert any("speaker=KOKODA|affinity=-16" in c for c in contents)
    # ...pero el vínculo con terceros no se filtra.
    assert not any("speaker=Mathias|affinity=60" in c for c in contents)
    assert any("speaker=Mathias|affinity=unknown" in c for c in contents)


def test_all_scope_exposes_every_speaker_affinity():
    state, _ = seed_group_state()
    llm = FakeLLM(replies=[KOKODA_REPLY])
    svc = make_service(llm, state, affinity_scope="all")

    run(svc.run_turn(KOKODA, [(KOKODA, "Airi que fácil eres")], TurnContext()))

    contents = [m["content"] for m in llm.calls[-1]["messages"][1:]]
    assert any("speaker=Mathias|affinity=60" in c for c in contents)
    assert any("speaker=KOKODA|affinity=-16" in c for c in contents)


def test_recipient_scope_hides_third_party_affinity():
    state, _ = seed_group_state()
    llm = FakeLLM(replies=[KOKODA_REPLY])
    svc = make_service(llm, state, affinity_scope="recipient")

    run(svc.run_turn(KOKODA, [(KOKODA, "Airi que fácil eres")], TurnContext()))

    contents = [m["content"] for m in llm.calls[-1]["messages"][1:]]
    assert any("speaker=KOKODA|affinity=-16" in c for c in contents)
    assert not any("speaker=Mathias|affinity=60" in c for c in contents)
    assert any("speaker=Mathias|affinity=unknown" in c for c in contents)
