"""Decisión y ejecución de la búsqueda web de Airi.

La decisión es una llamada de tool calling nativo: el modelo invoca (o no)
``buscar_web``. No hay regex ni heurísticas que disparen la búsqueda. El
resultado se convierte en un bloque de contexto y la voz de la respuesta queda
enteramente en manos del modelo.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from airi.domain.constants import (
    LLM_REASONING_BUDGET_LOW_TOKENS,
    SEARCH_QUERY_MAX_TOKENS,
)
from airi.domain.notices import web_search_notice
from airi.domain.prompts import WEB_SEARCH_DECISION_PROMPT
from airi.domain.web_tool import (
    WEB_SEARCH_TOOL,
    SearchRequest,
    parse_search_request,
    render_search_block,
)
from airi.ports.web_search import WebSearchNotes

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WebSearchOutcome:
    """Resultado de intentar usar la herramienta de búsqueda en un turno."""

    requested: bool = False
    request: SearchRequest | None = None
    notes: WebSearchNotes | None = None
    failed: bool = False
    prompt_block: str | None = None
    decision_ms: int = 0
    search_ms: int = 0
    notice_sent: bool = False
    finish_reason: str | None = None
    error: str | None = None


class WebSearchService:
    """Orquesta decisión → búsqueda → bloque de notas."""

    def __init__(self, *, llm, search=None, notifier=None):
        self.llm = llm
        self.search = search
        self.notifier = notifier

    async def run(
        self, *, current_text: str, context: str = ""
    ) -> WebSearchOutcome:
        decision_started = time.perf_counter()
        try:
            request, finish_reason = await self.decide(
                current_text=current_text, context=context
            )
        except Exception as exc:  # noqa: BLE001 - el turno no debe caerse
            log.exception("Falló la decisión de búsqueda web")
            return WebSearchOutcome(
                decision_ms=int(
                    (time.perf_counter() - decision_started) * 1000
                ),
                error=f"{type(exc).__name__}: {exc}",
            )
        decision_ms = int((time.perf_counter() - decision_started) * 1000)
        if request is None:
            return WebSearchOutcome(
                decision_ms=decision_ms, finish_reason=finish_reason
            )

        notice_sent = False
        if self.notifier is not None:
            try:
                await self.notifier.send(web_search_notice())
                notice_sent = True
            except Exception:  # noqa: BLE001 - el aviso es best-effort
                log.exception("No se pudo enviar el aviso de búsqueda")

        search_started = time.perf_counter()
        notes = None
        error = None
        if self.search is not None:
            try:
                notes = await self.search.search(request.query)
            except Exception as exc:  # noqa: BLE001 - se informa al modelo
                log.exception("Falló la búsqueda web")
                error = f"{type(exc).__name__}: {exc}"
        search_ms = int((time.perf_counter() - search_started) * 1000)

        failed = notes is None or notes.is_empty
        if failed:
            log.warning("La búsqueda web no devolvió notas útiles")

        return WebSearchOutcome(
            requested=True,
            request=request,
            notes=notes,
            failed=failed,
            prompt_block=render_search_block(request, notes, failed=failed),
            decision_ms=decision_ms,
            search_ms=search_ms,
            notice_sent=notice_sent,
            finish_reason=finish_reason,
            error=error,
        )

    async def decide(
        self, *, current_text: str, context: str = ""
    ) -> tuple[SearchRequest | None, str | None]:
        """Pregunta al modelo si necesita buscar. Sin respuesta = no busca."""
        if not current_text.strip():
            return None, None
        user_content = current_text
        if context:
            user_content = (
                "Contexto reciente de la conversación:\n"
                f"{context}\n\n"
                "Mensaje actual:\n"
                f"{current_text}"
            )
        messages = [
            {"role": "system", "content": WEB_SEARCH_DECISION_PROMPT},
            {"role": "user", "content": user_content},
        ]
        _content, meta = await self.llm.chat_with_meta(
            messages,
            tools=[WEB_SEARCH_TOOL],
            tool_choice="auto",
            max_tokens=SEARCH_QUERY_MAX_TOKENS,
            temperature=0.2,
            reasoning_budget_tokens=LLM_REASONING_BUDGET_LOW_TOKENS,
            quick_turn=True,
        )
        request = parse_search_request(getattr(meta, "tool_calls", None))
        return request, getattr(meta, "finish_reason", None)
