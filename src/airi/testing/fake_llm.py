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
                 metas=None):
        self.replies = list(replies or [])
        self.default_reply = default_reply
        self.strict_error = strict_error
        # Metadatos opcionales por respuesta (p. ej. finish_reason="length").
        self.metas = list(metas or [])
        self.calls = []  # dicts con messages/schema/max_tokens/temperature/...

    async def chat(self, messages, *, schema=None, max_tokens=None,
                   temperature=None, disable_thinking=False, strict_schema=False):
        content, _meta = await self.chat_with_meta(
            messages, schema=schema, max_tokens=max_tokens,
            temperature=temperature, disable_thinking=disable_thinking,
            strict_schema=strict_schema,
        )
        return content

    async def chat_with_meta(self, messages, *, schema=None, max_tokens=None,
                             temperature=None, disable_thinking=False,
                             strict_schema=False):
        self.calls.append({
            "messages": messages,
            "schema": schema,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "disable_thinking": disable_thinking,
            "strict_schema": strict_schema,
        })
        if strict_schema and self.strict_error is not None:
            raise self.strict_error
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