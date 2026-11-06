"""Contrato del revisor semántico y gate de activación."""

from __future__ import annotations

import asyncio
import json

from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeLLM, FakeUser, llm_json, make_state


def _review_json(**changes):
    result = {
        "on_topic": True,
        "right_addressee": True,
        "coherent": True,
        "issues": [],
    }
    result.update(changes)
    return json.dumps(result)


def _service(replies):
    state, _ = make_state()
    llm = FakeLLM(replies=replies)
    service = ConversationService(llm=llm, state=state)
    service.conversation_review_enabled = True
    return service, llm


def test_review_usa_prompt_de_juez_sin_personalidad_y_contexto_etiquetado():
    service, llm = _service([_review_json()])
    history = [
        {"role": "user", "author_name": "Ana", "content": "Me gusta el ramen."},
        {"role": "assistant", "content": '{"reply":"A mí también."}'},
    ]
    calls = []

    result = asyncio.run(
        service._review(
            calls,
            history=history,
            draft="A mí también me encanta.",
        )
    )

    assert result.valid is True
    assert len(llm.calls) == 1
    assert llm.calls[0]["messages"][0]["content"].startswith("Eres un evaluador")
    assert "Airi" not in llm.calls[0]["messages"][0]["content"]
    user_content = llm.calls[0]["messages"][1]["content"]
    assert "Ana" in user_content
    assert "Me gusta el ramen" in user_content
    assert "BORRADOR" in user_content
    assert calls[0]["purpose"] == "conversation_review"
    assert llm.calls[0]["reasoning_budget_tokens"] == 1024


def test_review_falla_abierto_si_el_llm_lanza():
    class BrokenLLM(FakeLLM):
        async def chat_with_meta(self, messages, **kwargs):
            raise TimeoutError("timeout del modelo")

    state, _ = make_state()
    service = ConversationService(llm=BrokenLLM(), state=state)

    result = asyncio.run(
        service._review([], history=[], draft="Borrador conversacional.")
    )

    assert result.valid is False


def test_should_review_tambien_en_1a1_y_salta_quick_date_y_silencio(monkeypatch):
    service, _ = _service([])
    monkeypatch.setattr(service, "conversation_review_enabled", True, raising=False)
    assert service._should_review(
        in_date=False, quick=False, kind="message", reply="Respuesta", session_mode=False
    )
    assert not service._should_review(
        in_date=False, quick=True, kind="message", reply="Respuesta", session_mode=False
    )
    assert not service._should_review(
        in_date=True, quick=False, kind="message", reply="Respuesta", session_mode=False
    )
    assert not service._should_review(
        in_date=False, quick=False, kind="message", reply="", session_mode=True
    )
    assert service._should_review(
        in_date=False, quick=False, kind="spectator", reply="Respuesta", session_mode=True
    )


def test_review_prompt_limita_historial_a_diez_entradas():
    service, llm = _service([_review_json()])
    history = [
        {"role": "user", "author_name": f"u{i}", "content": f"msg-{i}"}
        for i in range(14)
    ]
    result = asyncio.run(service._review([], history=history, draft="Respuesta"))
    assert result.valid
    content = llm.calls[0]["messages"][1]["content"]
    assert "msg-0" not in content
    assert "msg-13" in content


def test_turno_fuera_de_quick_revisa_y_repara_con_un_solo_borrador():
    state, _ = make_state()
    user = FakeUser(42, "Ana")
    llm = FakeLLM(
        replies=[
            llm_json("Me alegra que lo contaras; sigo pensando en lo que comentaste."),
            _review_json(
                on_topic=False,
                issues=[
                    {
                        "kind": "off_topic",
                        "impact": "breaks_thread",
                        "evidence": "sigo pensando en lo que comentaste",
                    }
                ],
            ),
            llm_json("Me alegra que lo contaras; esa parte me hizo reír bastante."),
        ]
    )
    service = ConversationService(llm=llm, state=state)
    service.conversation_review_enabled = True

    draft = asyncio.run(
        service.generate_turn(
            user,
            [(user, "cuéntame algo sobre la tarde de ayer " + "x" * 100)],
            TurnContext(),
        )
    )

    assert draft.output.reply == "Me alegra que lo contaras; esa parte me hizo reír bastante."
    assert [call["purpose"] for call in draft.trace.llm_calls] == [
        "primary",
        "conversation_review",
        "quality_repair",
    ]
    assert draft.trace.review_on_topic is False
    assert draft.trace.review_issues[0]["kind"] == "off_topic"
    assert isinstance(draft.trace.review_ms, int)
    assert draft.trace.repair_exhausted is False


def test_repair_exhausted_queda_en_traza_si_quality_repair_es_descartada():
    state, _ = make_state()
    user = FakeUser(42, "Ana")
    llm = FakeLLM(
        replies=[
            llm_json("Como modelo de lenguaje, prefiero hablar del clima."),
            _review_json(),
            llm_json("No."),
        ]
    )
    service = ConversationService(llm=llm, state=state)
    service.conversation_review_enabled = True

    draft = asyncio.run(
        service.generate_turn(
            user,
            [(user, "cuéntame algo sobre la tarde de ayer " + "x" * 100)],
            TurnContext(),
        )
    )

    assert draft.trace.repair_exhausted is True
    assert draft.trace.llm_calls[-1]["repair_reason"] == "ooc"
