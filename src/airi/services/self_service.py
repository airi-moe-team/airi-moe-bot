"""Reflexión introspectiva de Airi y autodescubrimiento."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from dataclasses import dataclass

from airi.domain.constants import (
    SELF_REFLECTION_MAX_TOKENS,
)
from airi.domain.llm_output import extract_json_object, parse_self_update
from airi.domain.prompts import SELF_REFLECTION_SCHEMA, self_reflection_prompt
from airi.domain.self_model import apply_self_update, sync_preferences_from_self
from airi.domain.text_filters import clean_reply
from airi.services.state import AppState

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReflectionOutcome:
    ran: bool = False
    discovery: str | None = None
    self_entry: dict | None = None

    @property
    def changed(self) -> bool:
        return bool(self.discovery or self.self_entry)


class SelfService:
    """Genera una reflexión y aplica sus efectos bajo el candado de commit."""

    def __init__(
        self,
        *,
        llm,
        state: AppState,
        clock=None,
        lock=None,
        persistence=None,
        max_tokens=SELF_REFLECTION_MAX_TOKENS,
    ):
        self.llm = llm
        self.state = state
        self.clock = clock
        self.lock = lock
        self.persistence = persistence
        self.max_tokens = max_tokens

    def _now(self, now):
        if now is not None:
            return now
        if self.clock is not None:
            return self.clock()
        import time as _time

        return _time.time()

    async def reflect(self, user_id, *, now=None, trigger="interaction", force=False):
        now = self._now(now)
        interactions = int(
            (self.state.users.get(str(user_id)) or {}).get("interactions", 0) or 0
        )
        if not self.state.should_reflect_self(
            interactions=interactions, now=now, force=force
        ):
            return ReflectionOutcome()

        model = self.state.self_model()
        notes = self.state.self_notes()
        prompt = self_reflection_prompt(
            model,
            user_name=self.state.display_name(user_id),
            diary=list(self.state.diary),
            now=now,
            notes=notes,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Responde ÚNICAMENTE con un objeto JSON válido que cumpla "
                    "el esquema. No escribas texto fuera del JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        raw = None
        try:
            if hasattr(self.llm, "chat_with_meta"):
                try:
                    raw, _meta = await self.llm.chat_with_meta(
                        messages,
                        schema=SELF_REFLECTION_SCHEMA,
                        strict_schema=True,
                        max_tokens=self.max_tokens,
                        disable_thinking=True,
                    )
                except Exception:
                    raw, _meta = await self.llm.chat_with_meta(
                        messages,
                        schema=SELF_REFLECTION_SCHEMA,
                        max_tokens=self.max_tokens,
                        disable_thinking=True,
                    )
            else:
                raw = await self.llm.chat(
                    messages,
                    schema=SELF_REFLECTION_SCHEMA,
                    max_tokens=self.max_tokens,
                    disable_thinking=True,
                )
        except Exception:
            log.info("Reflexión introspectiva no disponible (%s)", trigger)
            return ReflectionOutcome()

        parsed = extract_json_object(raw) if isinstance(raw, str) else None
        if not isinstance(parsed, dict):
            log.info("La reflexión no devolvió JSON válido")
            return ReflectionOutcome()

        discovery = parsed.get("discovery")
        discovery_text = clean_reply(discovery) if isinstance(discovery, str) else ""
        if discovery_text.strip().lower() in ("", "none", "ninguno", "null"):
            discovery_text = ""
        self_update = parse_self_update(parsed.get("self_update"))

        async with (self.lock or nullcontext()):
            context = (
                self.persistence.transaction()
                if self.persistence is not None
                else nullcontext()
            )
            with context:
                discovery_entry = None
                if discovery_text:
                    discovery_entry = self.state.add_self_note(
                        discovery_text,
                        now=now,
                        source=trigger,
                    )
                    if discovery_entry:
                        self.state.log_diary_event(
                            "discovery",
                            user_id,
                            f"Airi descubre: {discovery_text}",
                            now=now,
                        )
                self_entry = None
                if self_update:
                    self_entry = apply_self_update(
                        self.state.self_model(),
                        self_update,
                        now=now,
                        user_id=user_id,
                        source="reflection",
                    )
                    if self_entry:
                        sync_preferences_from_self(self.state.world)
                        self.state.save_identity()
                self.state.mark_self_reflection(now=now)

        return ReflectionOutcome(
            ran=True,
            discovery=discovery_entry["text"] if discovery_entry else None,
            self_entry=self_entry,
        )
