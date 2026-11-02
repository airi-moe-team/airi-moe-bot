"""Estado volátil y aislado de objetivos explícitos por canal y usuario."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from airi.domain.conversation_task import normalize_task_context_update


@dataclass(frozen=True)
class ConversationTaskFrame:
    goal: str
    constraints: tuple[str, ...]
    progress: str
    next_step: str
    updated_at: float
    expires_at: float

    def as_dict(self):
        return {
            "goal": self.goal,
            "constraints": list(self.constraints),
            "progress": self.progress,
            "next_step": self.next_step,
        }


class ConversationTaskRegistry:
    """Guarda un objetivo temporal sin escribirlo en el estado persistido."""

    def __init__(
        self, *, clock: Callable[[], float] | None = None,
        ttl_seconds=3600, max_frames=256,
    ):
        self._clock = clock or time.monotonic
        self._ttl_seconds = max(0.0, float(ttl_seconds))
        self._max_frames = max(1, int(max_frames))
        self._frames: dict[tuple[str, str], ConversationTaskFrame] = {}

    @staticmethod
    def _key(channel_id, user_id):
        return str(channel_id), str(user_id)

    def get(self, channel_id, user_id):
        key = self._key(channel_id, user_id)
        frame = self._frames.get(key)
        if frame is None:
            return None
        now = float(self._clock())
        if self._ttl_seconds <= 0 or now >= frame.expires_at:
            self._frames.pop(key, None)
            return None
        refreshed = ConversationTaskFrame(
            goal=frame.goal,
            constraints=frame.constraints,
            progress=frame.progress,
            next_step=frame.next_step,
            updated_at=frame.updated_at,
            expires_at=now + self._ttl_seconds,
        )
        self._frames[key] = refreshed
        return refreshed

    def apply(self, channel_id, user_id, raw_update):
        update = normalize_task_context_update(raw_update)
        if update["action"] == "none":
            return False
        key = self._key(channel_id, user_id)
        if update["action"] == "clear":
            return self._frames.pop(key, None) is not None
        now = float(self._clock())
        if self._ttl_seconds <= 0:
            self._frames.pop(key, None)
            return False
        self._prune_expired(now)
        if key not in self._frames and len(self._frames) >= self._max_frames:
            oldest = min(self._frames, key=lambda item: self._frames[item].expires_at)
            self._frames.pop(oldest, None)
        self._frames[key] = ConversationTaskFrame(
            goal=update["goal"],
            constraints=tuple(update["constraints"]),
            progress=update["progress"],
            next_step=update["next_step"],
            updated_at=now,
            expires_at=now + self._ttl_seconds,
        )
        return True

    def _prune_expired(self, now):
        expired = [
            key for key, frame in self._frames.items()
            if now >= frame.expires_at
        ]
        for key in expired:
            self._frames.pop(key, None)
        return len(expired)

    def clear(self, channel_id, user_id):
        return self._frames.pop(self._key(channel_id, user_id), None) is not None

    def clear_channel(self, channel_id):
        key = str(channel_id)
        stale = [frame_key for frame_key in self._frames if frame_key[0] == key]
        for frame_key in stale:
            self._frames.pop(frame_key, None)
        return len(stale)

    def clear_all(self):
        self._frames.clear()


__all__ = ["ConversationTaskFrame", "ConversationTaskRegistry"]
