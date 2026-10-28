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
    "status",
    "duration_ms",
    "finish_reason",
    "usage",
    "ttft_ms",
    "first_content_ms",
    "server_timings",
    "reasoning_present",
    "reasoning_tokens",
    "reasoning_deltas",
    "content_deltas",
    "max_tokens",
    "thinking_requested_off",
    "thinking_effective",
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
        "truncation_repair",
    ]
    assert trace.llm_calls[0]["finish_reason"] == "length"
    assert trace.llm_calls[1]["finish_reason"] == "stop"
    assert llm.calls[0]["force_disable_thinking"] is False
    assert llm.calls[1]["force_disable_thinking"] is True
    assert trace.llm_calls[0]["thinking_effective"] is True
    assert trace.llm_calls[1]["thinking_effective"] is False
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
        "empty_reply_repair",
    ]


def test_all_repair_calls_force_thinking_off_but_primary_follows_global_mode():
    llm = FakeLLM(
        replies=["", llm_json("respuesta")],
        metas=[LLMMeta(finish_reason="stop"), LLMMeta(finish_reason="stop")],
    )
    trace = _turn(llm, message="hola" + "x" * 100, thinking_mode="on")

    assert [call["purpose"] for call in trace.llm_calls] == [
        "primary",
        "empty_reply_repair",
    ]
    assert [call["force_disable_thinking"] for call in llm.calls] == [False, True]
    assert [call["thinking_effective"] for call in trace.llm_calls] == [True, False]


def test_question_close_repair_forces_thinking_off_in_global_on():
    llm = FakeLLM(
        replies=[llm_json("¿Qué opinas?"), llm_json("Me parece bien.")],
        metas=[LLMMeta(finish_reason="stop"), LLMMeta(finish_reason="stop")],
    )
    trace = _turn(
        llm,
        message="hola",
        thinking_mode="on",
        history=[{"role": "assistant", "content": "¿Qué tal?"}],
    )

    assert [call["purpose"] for call in trace.llm_calls] == [
        "primary",
        "question_close_repair",
    ]
    assert [call["force_disable_thinking"] for call in llm.calls] == [False, True]
    assert [call["thinking_effective"] for call in trace.llm_calls] == [True, False]


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
        "empty_reply_repair",
        "empty_reply_repair:json_object_retry",
    ]
    assert [call["force_disable_thinking"] for call in llm.calls] == [
        False,
        True,
        True,
    ]
    assert [call["thinking_effective"] for call in trace.llm_calls] == [
        True,
        False,
        False,
    ]


def test_primary_thinking_policy_is_not_changed_by_repair_override():
    """Un turno rápido mantiene thinking on, aunque su reparación lo pueda apagar."""
    llm = FakeLLM(replies=[llm_json("hola")])
    trace = _turn(llm, message="hola", thinking_mode="on")  # corto ⇒ turno rápido

    assert llm.calls[0]["disable_thinking"] is True  # lo que pidió el servicio
    assert trace.llm_calls[0]["thinking_requested_off"] is True
    assert trace.llm_calls[0]["thinking_effective"] is True
    assert llm.calls[0]["force_disable_thinking"] is False


def test_auto_mode_does_not_record_effective_thinking_on_for_quick_turns():
    llm = FakeLLM(replies=[llm_json("hola")])
    trace = _turn(llm, message="hola", thinking_mode="auto")

    assert trace.llm_calls[0]["thinking_requested_off"] is True
    assert trace.llm_calls[0]["thinking_effective"] is False
    assert llm.calls[0]["force_disable_thinking"] is False


def test_every_repair_purpose_uses_per_call_override():
    purposes = (
        "truncation_repair",
        "empty_reply_repair",
        "repeat_reply_repair",
        "question_close_repair",
        "disconnect_repair",
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
                disable_thinking=False,
            )
        return llm

    llm = asyncio.run(run_repair_calls())
    assert [call["force_disable_thinking"] for call in llm.calls] == [True] * 5
    assert all(call["disable_thinking"] is True for call in llm.calls)


def test_call_metadata_never_contains_private_text():
    llm = FakeLLM(replies=[llm_json("Respuesta también privada")])
    trace = _turn(llm, message=PRIVATE_TOKEN + " " + "x" * 200)

    serialized = json.dumps(trace.llm_calls, ensure_ascii=False)
    assert PRIVATE_TOKEN not in serialized
    assert "Respuesta también privada" not in serialized
