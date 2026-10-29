"""Metadatos por llamada al LLM: cuántas llamadas hubo, por qué y cuánto duraron.

El benchmark anterior solo conservaba la primera medición temporal y el último
`finish_reason`, así que una reparación invisible podía duplicar la latencia sin
dejar rastro. Estos tests fijan el contrato: cada invocación al modelo queda
registrada con su propósito, su `finish_reason` real y su duración, y sin texto
de prompt, historial ni respuesta.
"""

from __future__ import annotations

import asyncio
import json

from airi.ports.llm import LLMMeta
from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeLLM, FakeUser, llm_json, make_state

PRIVATE_TOKEN = "contenido-privado-de-prueba"

CALL_FIELDS = {
    "purpose",
    "repair_reason",
    "status",
    "duration_ms",
    "finish_reason",
    "usage",
    "ttft_ms",
    "first_content_ms",
    "server_timings",
    "reasoning_present",
    "reasoning_tokens",
    "reasoning_budget_tokens",
    "reasoning_deltas",
    "content_deltas",
    "max_tokens",
    "error_type",
}


def _turn(llm, message=PRIVATE_TOKEN, thinking_mode=None, history=None):
    state, _ = make_state()
    llm.thinking_mode = thinking_mode or "auto"
    if history is not None:
        state.histories[0] = list(history)
    user = FakeUser(42, "David")
    svc = ConversationService(llm=llm, state=state, clock=lambda: 1_000_000.0)
    result = asyncio.run(svc.run_turn(user, [(user, message)], TurnContext()))
    return result.trace


def test_normal_turn_records_one_primary_call():
    llm = FakeLLM(replies=[llm_json("hola")])
    trace = _turn(llm, thinking_mode="on")

    assert len(trace.llm_calls) == 1
    call = trace.llm_calls[0]
    assert call["purpose"] == "primary"
    assert call["status"] == "ok"
    assert call["reasoning_budget_tokens"] is None
    assert call["finish_reason"] == "stop"
    assert isinstance(call["duration_ms"], int)
    assert call["duration_ms"] >= 0
    assert set(call) == CALL_FIELDS


def test_truncated_first_call_keeps_its_finish_reason_and_repair_purpose():
    llm = FakeLLM(
        replies=["", llm_json("hola")],
        metas=[
            LLMMeta(finish_reason="length", usage={"completion_tokens": 6000}),
            LLMMeta(finish_reason="stop", usage={"completion_tokens": 120}),
        ],
    )
    trace = _turn(llm, thinking_mode="on")

    assert [call["purpose"] for call in trace.llm_calls] == [
        "primary",
        "parse_repair",
    ]
    assert trace.llm_calls[0]["finish_reason"] == "length"
    assert trace.llm_calls[1]["finish_reason"] == "stop"
    assert llm.calls[0]["reasoning_budget_tokens"] is None
    assert llm.calls[1]["reasoning_budget_tokens"] == 256
    assert trace.llm_calls[0]["reasoning_budget_tokens"] is None
    assert trace.llm_calls[1]["reasoning_budget_tokens"] == 256
    assert trace.llm_calls[1]["repair_reason"] == "truncation"
    # Compatibilidad: el campo agregado sigue describiendo la respuesta usada.
    assert trace.llm_finish_reason == "stop"


def test_empty_reply_repair_is_recorded_with_its_own_purpose():
    llm = FakeLLM(
        replies=["", llm_json("hola")],
        metas=[LLMMeta(finish_reason="stop"), LLMMeta(finish_reason="stop")],
    )
    trace = _turn(llm)

    assert [call["purpose"] for call in trace.llm_calls] == [
        "primary",
        "parse_repair",
    ]
    assert trace.llm_calls[1]["repair_reason"] == "empty"


def test_all_repair_calls_use_low_effort_but_primary_follows_global_mode():
    llm = FakeLLM(
        replies=["", llm_json("respuesta")],
        metas=[LLMMeta(finish_reason="stop"), LLMMeta(finish_reason="stop")],
    )
    trace = _turn(llm, message="hola" + "x" * 100, thinking_mode="on")

    assert [call["purpose"] for call in trace.llm_calls] == [
        "primary",
        "parse_repair",
    ]
    assert [call["reasoning_budget_tokens"] for call in llm.calls] == [None, 256]
    assert [call["reasoning_budget_tokens"] for call in trace.llm_calls] == [None, 256]


def test_question_close_is_repaired_deterministically_without_extra_call():
    llm = FakeLLM(
        replies=[llm_json("Me parece bien. ¿Qué opinas?")],
        metas=[LLMMeta(finish_reason="stop")],
    )
    trace = _turn(
        llm,
        message="hola",
        thinking_mode="on",
        history=[{"role": "assistant", "content": "¿Qué tal?"}],
    )

    assert [call["purpose"] for call in trace.llm_calls] == ["primary"]
    assert [call["reasoning_budget_tokens"] for call in llm.calls] == [None]
    assert [call["reasoning_budget_tokens"] for call in trace.llm_calls] == [None]


def test_repair_override_survives_json_schema_fallback():
    class StrictRepairFallbackLLM(FakeLLM):
        async def chat_with_meta(self, messages, **kwargs):
            call = {"messages": messages, **kwargs}
            self.calls.append(call)
            if len(self.calls) == 1:
                return "", LLMMeta(finish_reason="stop")
            if kwargs.get("strict_schema"):
                raise ValueError("json_schema unsupported")
            return llm_json("reparada"), LLMMeta(finish_reason="stop")

    llm = StrictRepairFallbackLLM()
    trace = _turn(llm, message=PRIVATE_TOKEN + " x" * 100, thinking_mode="on")

    assert [call["purpose"] for call in trace.llm_calls] == [
        "primary",
        "parse_repair",
        "parse_repair:json_object_retry",
    ]
    assert [call["reasoning_budget_tokens"] for call in llm.calls] == [None, 256, 256]
    assert [call["reasoning_budget_tokens"] for call in trace.llm_calls] == [
        None, 256, 256,
    ]


def test_primary_budget_policy_is_not_changed_by_repair_override():
    """Un turno rápido conserva el marcador y las reparaciones solicitan low."""
    llm = FakeLLM(replies=[llm_json("hola")])
    trace = _turn(llm, message="hola", thinking_mode="on")  # corto ⇒ turno rápido

    assert llm.calls[0]["quick_turn"] is True
    assert trace.llm_calls[0]["reasoning_budget_tokens"] is None


def test_auto_mode_quick_turn_records_low_budget():
    llm = FakeLLM(replies=[llm_json("hola")])
    trace = _turn(llm, message="hola", thinking_mode="auto")

    assert trace.llm_calls[0]["reasoning_budget_tokens"] == 256
    assert llm.calls[0]["quick_turn"] is True


def test_every_repair_purpose_uses_low_budget_override():
    purposes = (
        "parse_repair",
        "quality_repair",
    )

    async def run_repair_calls():
        state, _ = make_state()
        llm = FakeLLM(default_reply=llm_json("repair"))
        llm.thinking_mode = "on"
        service = ConversationService(llm=llm, state=state)
        for purpose in purposes:
            await service._chat(
                [],
                purpose,
                [{"role": "user", "content": "private"}],
                schema=None,
                max_tokens=20,
            )
        return llm

    llm = asyncio.run(run_repair_calls())
    assert [call["reasoning_budget_tokens"] for call in llm.calls] == [256] * 2


def test_call_metadata_never_contains_private_text():
    llm = FakeLLM(replies=[llm_json("Respuesta también privada")])
    trace = _turn(llm, message=PRIVATE_TOKEN + " " + "x" * 200)

    serialized = json.dumps(trace.llm_calls, ensure_ascii=False)
    assert PRIVATE_TOKEN not in serialized
    assert "Respuesta también privada" not in serialized
