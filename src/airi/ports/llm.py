"""Puerto: cliente de LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class LLMMeta:
    """Metadatos de una respuesta del modelo (además del texto)."""

    finish_reason: str | None = None
    usage: dict | None = field(default_factory=dict)
    ttft_ms: int | None = None
    first_content_ms: int | None = None
    server_timings: dict[str, int | float] | None = None
    reasoning_present: bool | None = None
    reasoning_tokens: int | None = None
    #: Presupuesto de reasoning solicitado por el cliente; no confirma que el
    #: backend lo haya aplicado.
    reasoning_budget_tokens: int | None = None
    #: Deltas SSE recibidos por canal. Son un proxy del reparto de tokens, no
    #: un conteo exacto: solo `usage` (si el servidor lo entrega) lo es.
    reasoning_deltas: int | None = None
    content_deltas: int | None = None
    payload_capture: "PayloadCaptureResult | None" = None
    response_capture: "PayloadCaptureResult | None" = None
    #: Tool calls normalizadas: ``{"id", "name", "arguments"}``. ``arguments``
    #: es un dict ya parseado; si el JSON era inválido, queda ``{}``.
    tool_calls: list[dict] | None = None


@dataclass
class LLMCallContext:
    """Metadatos locales de una llamada, nunca incluidos en el request HTTP."""

    correlation_id: str
    purpose: str
    call_index: int
    model: str | None = None
    provider: str | None = None
    payload_capture: "PayloadCaptureResult | None" = None
    response_capture: "PayloadCaptureResult | None" = None


@dataclass(frozen=True)
class PayloadCaptureResult:
    status: str
    artifact_ref: str | None = None
    sha256: str | None = None
    error: str | None = None


class LlmPayloadCapture(Protocol):
    async def capture(
        self, context: LLMCallContext, payload: dict
    ) -> PayloadCaptureResult: ...

    async def capture_response(
        self, context: LLMCallContext, output: dict
    ) -> PayloadCaptureResult: ...


class LLMClient(Protocol):
    """Cliente de LLM local (llama.cpp u otro compatible con OpenAI API)."""

    async def chat(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        max_tokens: int | None = None,
        reasoning_budget_tokens: int | None = None,
        quick_turn: bool = False,
        strict_schema: bool = False,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        call_context: LLMCallContext | None = None,
    ) -> str:
        """Devuelve el texto de la respuesta del modelo.

        `reasoning_budget_tokens` limita reasoning solo para esta llamada.
        `quick_turn` permite al adaptador elegir presupuesto sin apagar reasoning.
        `tools` activa tool calling nativo; no puede combinarse con `schema`.
        """
        ...

    async def chat_with_meta(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        max_tokens: int | None = None,
        reasoning_budget_tokens: int | None = None,
        quick_turn: bool = False,
        strict_schema: bool = False,
        stream: bool = False,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        call_context: LLMCallContext | None = None,
    ) -> tuple[str, LLMMeta]:
        """Igual que `chat` pero además devuelve los metadatos del turno."""
        ...
