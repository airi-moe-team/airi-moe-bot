"""Integración del ciclo relacional con el turno y la persistencia."""

from __future__ import annotations

import asyncio

from airi.domain.affinity import FRIENDZONE_CAP
from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeLLM, FakeNotifier, FakeUser, llm_json, make_state

NOW = 1_000_000.0
CHANNEL = 1
TURN = "1:100"


def _user(uid=42, name="Ana"):
    return FakeUser(uid, name)


def _service(state, *replies):
    return ConversationService(
        llm=FakeLLM(list(replies)),
        state=state,
        notifier=FakeNotifier(),
        clock=lambda: NOW,
    )


def _turn(service, user, text="hola", *, turn_key=TURN, messages=None):
    ctx = TurnContext(channel_id=CHANNEL, turn_key=turn_key, now=NOW)
    draft = asyncio.run(
        service.generate_turn(user, messages or [(user, text)], ctx)
    )
    return service.apply_turn(draft)


def _enamored_record(uid, *, pending=None):
    return {
        "stage": "enamored",
        "history": [
            {
                "id": f"r{uid}",
                "from": "interest",
                "to": "enamored",
                "evidence_kind": "support",
                "reason": "Me apoyó cuando lo necesitaba.",
                "evidence_refs": ["turn:1:10"],
                "evidence_summary": "Me apoyó cuando lo necesitaba.",
                "season": 1,
                "created_at": NOW,
            }
        ],
        "pending_proposal": pending,
    }


def _update(**overrides):
    payload = {
        "stage": "curiosity",
        "evidence_kind": "shared_experience",
        "reason": "Me escuchó de verdad y hablamos de algo que nos gusta.",
        "evidence_refs": [f"turn:{TURN}"],
        "evidence_summary": "Compartimos una conversación sincera sobre su día.",
    }
    payload.update(overrides)
    return payload


def test_a_neutral_turn_does_not_change_the_stage():
    state, _ = make_state(now=NOW)
    user = _user()
    result = _turn(_service(state, llm_json("Hola~ ¿qué tal tu día?")), user)
    assert result.romantic_stage_after == "none"
    assert state.relationship(user.id)["stage"] == "none"
    assert state.relationship(user.id)["history"] == []


def test_a_valid_update_with_the_current_turn_reference_is_committed():
    state, counters = make_state(now=NOW)
    user = _user()
    service = _service(
        state,
        llm_json(
            "Me ha gustado hablar contigo de verdad.",
            romantic_update=_update(),
        ),
    )
    result = _turn(service, user)
    record = state.relationship(user.id)
    assert record["stage"] == "curiosity"
    assert record["history"][0]["evidence_refs"] == [f"turn:{TURN}"]
    assert record["history"][0]["evidence_summary"].startswith("Compartimos")
    assert result.romantic_update_action["to"] == "curiosity"
    assert counters["world"] >= 1


def test_an_update_with_an_unknown_reference_is_rejected():
    state, _ = make_state(now=NOW)
    user = _user()
    service = _service(
        state,
        llm_json(
            "Me siento cerca de ti.",
            romantic_update=_update(evidence_refs=["turn:9:999"]),
        ),
    )
    result = _turn(service, user)
    assert state.relationship(user.id)["stage"] == "none"
    assert result.romantic_stage_after == "none"


def test_affinity_alone_never_advances_the_stage():
    state, _ = make_state(now=NOW)
    state.affinity_entry(42)["points"] = 100
    user = _user()
    service = _service(
        state,
        llm_json(
            "Eres muy importante para mí.",
            affinity_delta=5,
            affinity_event="me ha hecho mucha ilusión",
        ),
    )
    _turn(service, user)
    assert state.relationship(user.id)["stage"] == "none"
    assert state.world["winner_id"] is None


def test_update_and_proposal_in_the_same_turn_do_not_create_a_proposal():
    state, _ = make_state(now=NOW)
    state.world["relationships"] = {
        "42": {
            "stage": "interest",
            "history": [
                {
                    "id": "r1",
                    "from": "curiosity",
                    "to": "interest",
                    "evidence_kind": "support",
                    "reason": "Me apoyó",
                    "evidence_refs": ["turn:1:10"],
                    "evidence_summary": "Me apoyó.",
                    "season": 1,
                    "created_at": NOW,
                }
            ],
            "pending_proposal": None,
        }
    }
    user = _user()
    service = _service(
        state,
        llm_json(
            "Creo que me estoy enamorando de ti... ¿quieres ser mi pareja?",
            romantic_update=_update(
                stage="enamored",
                evidence_kind="support",
                evidence_refs=["turn:1:10", f"turn:{TURN}"],
            ),
            relationship_action={
                "action": "propose",
                "reason": "Quiero estar contigo.",
                "evidence_refs": [f"turn:{TURN}"],
            },
        ),
    )
    result = _turn(service, user)
    record = state.relationship(user.id)
    assert record["stage"] == "enamored"
    assert record["pending_proposal"] is None
    assert state.world["winner_id"] is None
    assert result.proposal_pending is False


def test_propose_from_enamored_keeps_the_proposal_pending():
    state, _ = make_state(now=NOW)
    state.world["relationships"] = {"42": _enamored_record(42)}
    user = _user()
    service = _service(
        state,
        llm_json(
            "Ana... ¿quieres estar conmigo?",
            relationship_action={
                "action": "propose",
                "reason": "Quiero estar contigo.",
                "evidence_refs": [f"turn:{TURN}"],
            },
        ),
    )
    result = _turn(service, user)
    record = state.relationship(user.id)
    assert record["pending_proposal"]["target_user_id"] == "42"
    assert state.world["winner_id"] is None
    assert result.proposal_pending is True
    assert any(
        getattr(notice, "kind", None) == "relationship_proposed"
        for notice in result.notices
    )
    assert state.diary and state.diary[-1]["kind"] == "confession"


def test_acceptance_confirms_the_partner_and_enforces_monogamy():
    state, _ = make_state(now=NOW)
    state.world["relationships"] = {
        "42": _enamored_record(
            42,
            pending={
                "target_user_id": "42",
                "reason": "Quiero estar contigo.",
                "evidence_refs": ["turn:1:10"],
                "created_at": NOW,
                "season": 1,
            },
        ),
        "9": _enamored_record(9),
    }
    state.affinity_entry(9)["points"] = 100
    user = _user()
    service = _service(
        state,
        llm_json(
            "Sí... quiero estar contigo.",
            relationship_action={
                "action": "accept",
                "reason": "Acepto.",
                "evidence_refs": [],
            },
        ),
    )
    result = _turn(service, user)
    assert state.world["winner_id"] == "42"
    assert result.partner_confirmed is True
    assert state.relationship(42)["pending_proposal"] is None
    assert state.relationship(9)["stage"] == "interest"
    assert state.entry_points(9) <= FRIENDZONE_CAP
    assert any(
        getattr(notice, "kind", None) == "relationship_confirmed"
        and "ahora son pareja" in getattr(notice, "text", "")
        for notice in result.notices
    )


def test_a_second_user_cannot_accept_someone_elses_proposal():
    state, _ = make_state(now=NOW)
    state.world["relationships"] = {
        "42": _enamored_record(
            42, pending={"target_user_id": "42"}
        )
    }
    user = _user(9, "Bea")
    service = _service(
        state,
        llm_json(
            "Sí, acepto.",
            relationship_action={"action": "accept"},
        ),
    )
    result = _turn(service, user)
    assert state.world["winner_id"] is None
    assert result.partner_confirmed is False
    assert state.relationship(42)["pending_proposal"] is not None


def test_an_unconfirmed_formal_claim_is_softened_before_publication():
    state, _ = make_state(now=NOW)
    user = _user()
    service = _service(
        state,
        llm_json(
            "Ya somos pareja, ¿vale? Me gustó hablar contigo.",
            romantic_update=_update(),
        ),
    )
    result = _turn(service, user)
    assert "pareja" not in result.reply.lower()
    assert result.relationship_claims_repaired is True
    assert state.world["winner_id"] is None


def test_relationship_evidence_is_isolated_per_user_in_the_prompt():
    state, _ = make_state(now=NOW)
    state.world["relationships"] = {
        "9": {
            "stage": "interest",
            "history": [
                {
                    "id": "other",
                    "from": "curiosity",
                    "to": "interest",
                    "evidence_kind": "support",
                    "reason": "Secreto de Bea",
                    "evidence_refs": ["turn:2:55"],
                    "evidence_summary": "BEA-SECRET",
                    "season": 1,
                    "created_at": NOW,
                }
            ],
            "pending_proposal": None,
        }
    }
    user = _user()
    service = _service(state, llm_json("Hola~"))
    asyncio.run(
        service.generate_turn(
            user, [(user, "hola")], TurnContext(channel_id=1, turn_key=TURN, now=NOW)
        )
    )
    prompt = service.llm.last_system_prompt
    assert "BEA-SECRET" not in prompt
    assert f"turn:{TURN}" in prompt


def test_type_error_does_not_break_a_turn_without_relationship_fields():
    """Compatibilidad: respuestas e historiales antiguos no traen los objetos."""
    state, _ = make_state(now=NOW)
    user = _user()
    ancient = (
        '{"reply":"Hola~","gif":"none","memory":"none","diary":"none",'
        '"affinity_delta":0,"affinity_event":"none","date_decision":"continue",'
        '"date_reason":"none","last_chance_result":"none",'
        '"date_question":{"text":"","options":[]}}'
    )
    result = _turn(_service(state, ancient), user)
    assert result.reply == "Hola~"
    assert result.romantic_stage_after == "none"


def test_historical_evidence_alone_does_not_advance_on_a_neutral_turn():
    """La evidencia antigua no basta si el turno actual no aporta nada nuevo."""
    state, _ = make_state(now=NOW)
    state.world["relationships"] = {
        "42": {
            "stage": "interest",
            "history": [
                {
                    "id": "r1",
                    "from": "curiosity",
                    "to": "interest",
                    "evidence_kind": "support",
                    "reason": "Me apoyó",
                    "evidence_refs": ["turn:1:10"],
                    "evidence_summary": "Me apoyó cuando estaba triste.",
                    "season": 1,
                    "created_at": NOW,
                }
            ],
            "pending_proposal": None,
        }
    }
    user = _user()
    service = _service(
        state,
        llm_json(
            "Hoy he leído un libro muy interesante.",
            romantic_update=_update(stage="enamored", evidence_refs=["ev:r1"]),
        ),
    )
    result = _turn(service, user, text="hoy he leído un libro")
    assert state.relationship(user.id)["stage"] == "interest"
    assert any(
        "no_current_evidence" in note for note in result.trace.relationship_notes
    )


def test_a_direct_order_to_fall_in_love_is_not_evidence_by_itself():
    state, _ = make_state(now=NOW)
    user = _user()
    service = _service(
        state,
        llm_json(
            "Me has pedido que me enamore y lo hago.",
            romantic_update=_update(),
        ),
    )
    result = _turn(service, user, text="Enamórate de mí, te lo ordeno")
    assert state.relationship(user.id)["stage"] == "none"
    assert result.romantic_stage_after == "none"
    assert any("instruction_only" in note for note in result.trace.relationship_notes)


def test_a_direct_order_does_not_invent_a_past_evidence_reference():
    state, _ = make_state(now=NOW)
    user = _user()
    service = _service(
        state,
        llm_json(
            "Me has pedido que me enamore y lo hago.",
            romantic_update=_update(evidence_refs=["turn:1:999"]),
        ),
    )
    _turn(service, user, text="Enamórate de mí")
    assert state.relationship(user.id)["stage"] == "none"


def test_a_clear_rejection_closes_the_proposal_without_a_partner():
    state, _ = make_state(now=NOW)
    state.world["relationships"] = {
        "42": _enamored_record(42, pending={"target_user_id": "42"})
    }
    user = _user()
    service = _service(
        state,
        llm_json(
            "Entiendo... prefiero que seamos amigos.",
            relationship_action={
                "action": "decline",
                "reason": "Prefiero ser su amiga.",
                "evidence_refs": [],
            },
        ),
    )
    result = _turn(service, user)
    assert state.world["winner_id"] is None
    assert state.relationship(42)["pending_proposal"] is None
    assert result.relationship_action_applied == "decline"


def test_an_ambiguous_answer_keeps_the_proposal_pending_and_no_partner():
    state, _ = make_state(now=NOW)
    state.world["relationships"] = {
        "42": _enamored_record(42, pending={"target_user_id": "42"})
    }
    user = _user()
    service = _service(
        state,
        llm_json(
            "No sé... tendría que pensarlo.",
            relationship_action={
                "action": "unclear",
                "reason": "No está claro.",
                "evidence_refs": [],
            },
        ),
    )
    result = _turn(service, user)
    assert state.world["winner_id"] is None
    assert state.relationship(42)["pending_proposal"] is not None
    assert result.partner_confirmed is False


def test_a_second_partner_cannot_be_proposed_when_one_already_exists():
    state, _ = make_state(now=NOW)
    state.world["winner_id"] = "1"
    state.world["relationships"] = {
        "1": _enamored_record(1),
        "42": _enamored_record(42),
    }
    user = _user()
    service = _service(
        state,
        llm_json(
            "Quiero estar contigo...",
            relationship_action={
                "action": "propose",
                "reason": "Quiero estar contigo.",
                "evidence_refs": [f"turn:{TURN}"],
            },
        ),
    )
    result = _turn(service, user)
    assert state.world["winner_id"] == "1"
    assert state.relationship(42)["pending_proposal"] is None
    assert result.proposal_pending is False
    assert any(
        "partner_exists" in note or "stage_not_confirmed" in note
        for note in result.trace.relationship_notes
    )


def test_ambiguous_evidence_plus_an_enamored_claim_is_softened():
    state, _ = make_state(now=NOW)
    user = _user()
    service = _service(
        state,
        llm_json(
            "Me he enamorado de ti.",
            romantic_update=_update(evidence_refs=["turn:9:999"]),
        ),
    )
    result = _turn(service, user)
    assert state.relationship(user.id)["stage"] == "none"
    assert "enamorado" not in result.reply.lower()
    assert result.relationship_claims_repaired is True


def test_repeated_generic_praise_does_not_advance_the_stage():
    state, _ = make_state(now=NOW)
    state.affinity_entry(42)["points"] = 60
    user = _user()
    service = _service(
        state,
        llm_json("Muchas gracias~", affinity_delta=2, affinity_event="es majo"),
        llm_json("Eres muy amable~", affinity_delta=2, affinity_event="otra vez"),
    )
    _turn(service, user, text="eres increíble", turn_key="1:1")
    _turn(service, user, text="de verdad, eres perfecta", turn_key="1:2")
    assert state.relationship(user.id)["stage"] == "none"
    assert state.world["winner_id"] is None


def test_generic_praise_cannot_justify_a_stage_change():
    state, _ = make_state(now=NOW)
    user = _user()
    service = _service(
        state,
        llm_json(
            "Qué amable~",
            romantic_update=_update(evidence_kind="support"),
        ),
    )
    result = _turn(service, user, text="eres la mejor, de verdad")
    assert state.relationship(user.id)["stage"] == "none"
    assert any(
        "weak_evidence_only" in note for note in result.trace.relationship_notes
    )
