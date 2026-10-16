"""Servicio de autodescubrimiento reflexivo de Airi."""

from __future__ import annotations

import logging

from airi.domain.constants import (
    SELF_REFLECTION_EVERY_N,
    SELF_REFLECTION_MAX_TOKENS,
    SELF_REFLECTION_MIN_INTERVAL,
)
from airi.domain.llm_output import parse_model_output
from airi.domain.prompts import SELF_REFLECTION_SCHEMA, self_reflection_prompt
from airi.domain.text_filters import clean_reply
from airi.services.state import AppState

log = logging.getLogger(__name__)


class SelfService:
    """Gestiona la reflexión introspectiva de Airi."""

    def __init__(
        self,
        *,
        llm,
        state: AppState,
        clock=None,
        every_n=SELF_REFLECTION_EVERY_N,
        min_interval=SELF_REFLECTION_MIN_INTERVAL,
        max_tokens=SELF_REFLECTION_MAX_TOKENS,
    ):
        self.llm = llm
        self.state = state
        self.clock = clock
        self.every_n = every_n
        self.min_interval = min_interval
        self.max_tokens = max_tokens

    async def reflect(self, user_id, *, now=None, trigger="interaction", force=False):
        """Ejecuta una reflexión introspectiva. Best-effort, devuelve True si ocurrió algo."""
        now = self._now(now)
        interactions = int((self.state.users.get(str(user_id)) or {}).get("interactions", 0) or 0)
        model = self.state.self_model()
        if not self.state.should_reflect_self(
            interactions=interactions, now=now, force=force
        ):
            return False
        user_name = self.state.display_name(user_id)
        diary = list(self.state.diary)
        system = (
            "Responde ÚNICAMENTE con un objeto JSON válido que cumpla con el "
            "esquema. No escribas texto fuera del JSON."
        )
        user_prompt = self_reflection_prompt(
            model, user_name=user_name, diary=diary, now=now
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]
        try:
            if hasattr(self.llm, "chat_with_meta"):
                raw, meta = await self.llm.chat_with_meta(
                    messages,
                    schema=SELF_REFLECTION_SCHEMA,
                    strict_schema=True,
                    max_tokens=self.max_tokens,
                    disable_thinking=True,
                )
                _ = meta
            else:
                raw = await self.llm.chat(
                    messages,
                    schema=SELF_REFLECTION_SCHEMA,
                    max_tokens=self.max_tokens,
                    disable_thinking=True,
                )
        except Exception:
            try:
                if hasattr(self.llm, "chat_with_meta"):
                    raw, meta = await self.llm.chat_with_meta(
                        messages,
                        schema=SELF_REFLECTION_SCHEMA,
                        max_tokens=self.max_tokens,
                        disable_thinking=True,
                    )
                    _ = meta
                else:
                    raw = await self.llm.chat(
                        messages,
                        schema=SELF_REFLECTION_SCHEMA,
                        max_tokens=self.max_tokens,
                        disable_thinking=True,
                    )
            except Exception:
                log.info("Reflexión introspectiva no disponible (%s)", trigger)
                return False
        output = parse_model_output(raw, delta_max=100)  # delta_max no aplica
        _ = output
        parsed = parse_model_output(raw).self_update  # get raw? easier: parse
        # Better: directly inspect parsed dict via extract pattern; simpler
        from airi.domain.llm_output import extract_json_object

        jd = extract_json_object(raw) if isinstance(raw, str) else None
        changed = False
        if isinstance(jd, dict):
            disc = jd.get("discovery")
            if isinstance(disc, str) and disc.strip().lower() not in ("", "none", "ninguno"):
                disc = clean_reply(disc).strip()[:300]
                if disc:
                    if self.state.add_self_discovery(disc, now=now, source="reflection"):
                        changed = True
                        self.state.log_diary_event(
                            "discovery",
                            user_id,
                            f"Airi descubre: {disc}",
                            now=now,
                        )
            su = jd.get("self_update")
            if su:
                entry = self.state.apply_self_change(
                    su, now=now, user_id=user_id, source="reflection"
                )
                if entry is not None:
                    changed = True
        self.state.mark_self_reflection(now=now)
        return changed

    def _now(self, now):
        if now is not None:
            return now
        if self.clock is not None:
            return self.clock()
        import time as _time

        return _time.time()
