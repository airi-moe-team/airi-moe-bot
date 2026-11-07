"""Doble falso del puerto LLM: devuelve respuestas guionizadas."""

from __future__ import annotations

import json

from airi.ports.llm import LLMMeta


def llm_json(reply, **fields):
    """Construye una respuesta JSON válida del modelo para tests."""
    payload = {
        "reply": reply,
        "gif": "none",
        "memory": "none",
        "diary": "none",
        "affinity_delta": 0,
        "affinity_event": "none",
        "date_decision": "continue",
        "date_reason": "none",
        "last_chance_result": "none",
        "date_question": {"text": "", "options": []},
    }
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False)


class FakeLLM:
    """Implementa `airi.ports.llm.LLMClient` con una cola de respuestas.

    `strict_error` (si se pasa) se lanza en las llamadas con `strict_schema=True`
    para simular un servidor que no soporta salida estructurada estricta.
    """

    def __init__(self, replies=None, default_reply="{}", strict_error=None,
                 metas=None, tool_calls=None, decision_replies=None):
        self.replies = list(replies or [])
        self.default_reply = default_reply
        self.strict_error = strict_error
        # Metadatos opcionales por respuesta (p. ej. finish_reason="length").
        self.metas = list(metas or [])
        # Cola de tool_calls por turno: cada entrada es la lista que devuelve
        # la llamada de decisión. Si está vacía, la decisión responde
        # NO_SEARCH sin consumir la cola de respuestas finales.
        self.tool_calls = list(tool_calls or [])
        # Respuestas crudas opcionales para la decisión (para simular que el
        # modelo contesta en texto en vez de llamar a la herramienta).
        self.decision_replies = list(decision_replies or [])
        self.calls = []  # dicts con messages/schema/max_tokens/...
        self.decision_calls = []  # llamadas de tool-decision separadas

    async def chat(self, messages, *, schema=None, max_tokens=None,
                   reasoning_budget_tokens=None, quick_turn=False,
                   strict_schema=False, stream=False, tools=None,
                   tool_choice=None, call_context=None):
        content, _meta = await self.chat_with_meta(
            messages, schema=schema, max_tokens=max_tokens,
            reasoning_budget_tokens=reasoning_budget_tokens,
            quick_turn=quick_turn,
            strict_schema=strict_schema, stream=stream,
            tools=tools, tool_choice=tool_choice, call_context=call_context,
        )
        return content

    async def chat_with_meta(self, messages, *, schema=None, max_tokens=None,
                             reasoning_budget_tokens=None,
                             quick_turn=False, strict_schema=False, stream=False,
                             tools=None, tool_choice=None, call_context=None):
        call = {
            "messages": messages,
            "schema": schema,
            "max_tokens": max_tokens,
            "reasoning_budget_tokens": reasoning_budget_tokens,
            "quick_turn": quick_turn,
            "strict_schema": strict_schema,
            "tools": tools,
            "tool_choice": tool_choice,
            "call_context": call_context,
        }
        if stream:
            call["stream"] = True
        (self.decision_calls if tools else self.calls).append(call)
        if strict_schema and self.strict_error is not None:
            raise self.strict_error
        if tools:
            if self.tool_calls:
                calls = self.tool_calls.pop(0)
                return "", LLMMeta(
                    finish_reason="tool_calls", usage={}, tool_calls=calls
                )
            if self.decision_replies:
                return self.decision_replies.pop(0), LLMMeta(
                    finish_reason="stop", usage={}
                )
            return "NO_SEARCH", LLMMeta(finish_reason="stop", usage={})
        meta = (
            self.metas.pop(0)
            if self.metas
            else LLMMeta(finish_reason="stop", usage={})
        )
        if self.replies:
            return self.replies.pop(0), meta
        return self.default_reply, meta

    @property
    def last_system_prompt(self):
        if not self.calls:
            return ""
        first = self.calls[-1]["messages"][0]
        return first.get("content", "") if first.get("role") == "system" else ""

    # ------------------------------------------------------------------
    # Modo replay: devuelve raw_llm guardado sin parsing
    # ------------------------------------------------------------------

    def replay_from_raw(self, raw_string: str):
        """Modo replay: la próxima llamada devuelve `raw_string` tal cual.

        Útil para `airi.replay` que necesita la respuesta cruda del modelo.
        """
        self.replies = [raw_string]
        self.metas = []
