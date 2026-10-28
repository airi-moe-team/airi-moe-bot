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
    #: Deltas SSE recibidos por canal. Son un proxy del reparto de tokens, no
    #: un conteo exacto: solo `usage` (si el servidor lo entrega) lo es.
    reasoning_deltas: int | None = None
    content_deltas: int | None = None


class LLMClient(Protocol):
    """Cliente de LLM local (llama.cpp u otro compatible con OpenAI API)."""

    async def chat(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        disable_thinking: bool = False,
        force_disable_thinking: bool = False,
        strict_schema: bool = False,
    ) -> str:
        """Devuelve el texto de la respuesta del modelo.

        `disable_thinking` desactiva el razonamiento del modelo si lo soporta.
        """
        ...

    async def chat_with_meta(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        disable_thinking: bool = False,
        force_disable_thinking: bool = False,
        strict_schema: bool = False,
        stream: bool = False,
    ) -> tuple[str, LLMMeta]:
        """Igual que `chat` pero además devuelve los metadatos del turno."""
        ...
