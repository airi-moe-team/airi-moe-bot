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

import aiohttp

from airi.ports.llm import LLMCallContext, LLMMeta, PayloadCaptureResult
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
    trace = _turn(llm, message=PRIVATE_TOKEN + " x" * 100, thinking_mode="auto")

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
    trace = _turn(llm, message=PRIVATE_TOKEN + " x" * 100, thinking_mode="auto")

    assert [call["purpose"] for call in trace.llm_calls] == [
        "primary",
        "parse_repair",
    ]
    assert trace.llm_calls[0]["finish_reason"] == "length"
    assert trace.llm_calls[1]["finish_reason"] == "stop"
    assert llm.calls[0]["reasoning_budget_tokens"] is None
    assert llm.calls[1]["reasoning_budget_tokens"] == 1024
    assert trace.llm_calls[0]["reasoning_budget_tokens"] is None
    assert trace.llm_calls[1]["reasoning_budget_tokens"] == 1024
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


def test_all_repair_calls_use_medium_budget_but_primary_follows_global_mode():
    llm = FakeLLM(
        replies=["", llm_json("respuesta")],
        metas=[LLMMeta(finish_reason="stop"), LLMMeta(finish_reason="stop")],
    )
    trace = _turn(llm, message="hola" + "x" * 100, thinking_mode="auto")

    assert [call["purpose"] for call in trace.llm_calls] == [
        "primary",
        "parse_repair",
    ]
    assert [call["reasoning_budget_tokens"] for call in llm.calls] == [None, 1024]
    assert [call["reasoning_budget_tokens"] for call in trace.llm_calls] == [None, 1024]


def test_question_close_is_repaired_deterministically_without_extra_call():
    llm = FakeLLM(
        replies=[llm_json("Me parece bien. ¿Qué opinas?")],
        metas=[LLMMeta(finish_reason="stop")],
    )
    trace = _turn(
        llm,
        message="hola",
        thinking_mode="auto",
        history=[{"role": "assistant", "content": "¿Qué tal?"}],
    )

    assert [call["purpose"] for call in trace.llm_calls] == ["primary"]
    assert [call["reasoning_budget_tokens"] for call in llm.calls] == [None]
    assert [call["reasoning_budget_tokens"] for call in trace.llm_calls] == [1024]


def test_repair_override_survives_json_schema_fallback():
    class StrictRepairFallbackLLM(FakeLLM):
        async def chat_with_meta(self, messages, **kwargs):
            if kwargs.get("tools"):
                self.decision_calls.append({"messages": messages, **kwargs})
                return "NO_SEARCH", LLMMeta(finish_reason="stop")
            call = {"messages": messages, **kwargs}
            self.calls.append(call)
            if len(self.calls) == 1:
                return "", LLMMeta(finish_reason="stop")
            if kwargs.get("strict_schema"):
                raise ValueError("json_schema unsupported")
            return llm_json("reparada"), LLMMeta(finish_reason="stop")

    llm = StrictRepairFallbackLLM()
    trace = _turn(llm, message=PRIVATE_TOKEN + " x" * 100, thinking_mode="auto")

    assert [call["purpose"] for call in trace.llm_calls] == [
        "primary",
        "parse_repair",
        "parse_repair:json_object_retry",
    ]
    assert [call["reasoning_budget_tokens"] for call in llm.calls] == [None, 1024, 1024]
    assert [call["reasoning_budget_tokens"] for call in trace.llm_calls] == [
        None, 1024, 1024,
    ]


def test_primary_budget_policy_is_not_changed_by_repair_override():
    """Auto rápido usa medium y la reparación no altera el modo global."""
    llm = FakeLLM(replies=[llm_json("hola")])
    trace = _turn(llm, message="hola", thinking_mode="auto")  # corto ⇒ turno rápido

    assert llm.calls[0]["quick_turn"] is True
    assert trace.llm_calls[0]["reasoning_budget_tokens"] == 1024


def test_auto_mode_quick_turn_records_medium_budget():
    llm = FakeLLM(replies=[llm_json("hola")])
    trace = _turn(llm, message="hola", thinking_mode="auto")

    assert trace.llm_calls[0]["reasoning_budget_tokens"] == 1024
    assert llm.calls[0]["quick_turn"] is True


def test_every_repair_purpose_uses_medium_budget_override():
    purposes = (
        "parse_repair",
        "quality_repair",
    )

    async def run_repair_calls():
        state, _ = make_state()
        llm = FakeLLM(default_reply=llm_json("repair"))
        llm.thinking_mode = "auto"
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
    assert [call["reasoning_budget_tokens"] for call in llm.calls] == [1024] * 2


def test_call_metadata_never_contains_private_text():
    llm = FakeLLM(replies=[llm_json("Respuesta también privada")])
    trace = _turn(llm, message=PRIVATE_TOKEN + " " + "x" * 200)

    serialized = json.dumps(trace.llm_calls, ensure_ascii=False)
    assert PRIVATE_TOKEN not in serialized
    assert "Respuesta también privada" not in serialized


def test_payload_capture_metadata_is_correlated_per_llm_call():
    class CaptureAwareLLM(FakeLLM):
        def __init__(self):
            super().__init__(replies=["", llm_json("reparada")])
            self.payload_capture = object()
            self.contexts = []

        async def chat_with_meta(self, messages, **kwargs):
            context = kwargs.get("call_context")
            assert isinstance(context, LLMCallContext)
            context.payload_capture = PayloadCaptureResult(
                "captured",
                artifact_ref=f"{context.correlation_id}/call-{context.call_index}.json",
                sha256=f"hash-{context.call_index}",
            )
            context.response_capture = PayloadCaptureResult(
                "captured",
                artifact_ref=(
                    f"{context.correlation_id}/call-{context.call_index}.response.json"
                ),
                sha256=f"response-hash-{context.call_index}",
            )
            self.contexts.append(context)
            return await super().chat_with_meta(messages, **{
                key: value for key, value in kwargs.items() if key != "call_context"
            })

    llm = CaptureAwareLLM()
    trace = _turn(llm)

    assert [context.purpose for context in llm.contexts] == [
        "web_search_decision", "primary", "parse_repair"
    ]
    assert [context.call_index for context in llm.contexts] == [1, 2, 3]
    assert all(context.correlation_id == trace.correlation_id for context in llm.contexts)
    assert [call["payload_capture"]["sha256"] for call in trace.llm_calls] == [
        "hash-1", "hash-2", "hash-3",
    ]
    assert [call["response_capture"]["sha256"] for call in trace.llm_calls] == [
        "response-hash-1", "response-hash-2", "response-hash-3",
    ]


def test_capture_reference_survives_http_failure_after_request_capture():
    class FailingCaptureLLM(FakeLLM):
        def __init__(self):
            super().__init__()
            self.payload_capture = object()

        async def chat_with_meta(self, messages, **kwargs):
            context = kwargs["call_context"]
            context.payload_capture = PayloadCaptureResult(
                "captured", "cid/call.json", "sha256"
            )
            raise aiohttp.ClientConnectionError("backend unavailable")

    async def invoke():
        state, _ = make_state()
        service = ConversationService(llm=FailingCaptureLLM(), state=state)
        calls = []
        try:
            await service._chat(
                calls,
                "primary",
                [{"role": "user", "content": "private"}],
                schema=None,
                max_tokens=20,
            )
        except aiohttp.ClientConnectionError:
            pass
        return calls

    calls = asyncio.run(invoke())

    assert calls[0]["status"] == "failed"
    assert calls[0]["payload_capture"] == {
        "status": "captured",
        "artifact_ref": "cid/call.json",
        "sha256": "sha256",
    }
