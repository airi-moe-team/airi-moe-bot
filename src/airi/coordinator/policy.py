"""Validated coordinator settings; values belong to the channel, not a bot."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ParticipationPolicy:
    proactive_enabled: bool = True
    idle_seconds: float = 1800
    cooldown_seconds: float = 10800
    max_per_day: int = 3
    recheck_seconds: float = 1800
    max_interventions: int = 6
    turn_delay_seconds: float = 8
    timezone: str = "America/Lima"
    start_hour: int = 9
    end_hour: int = 23

    def __post_init__(self):
        if not isinstance(self.proactive_enabled, bool):
            raise ValueError("proactive_enabled must be a boolean")
        for field in ("idle_seconds", "cooldown_seconds", "recheck_seconds", "turn_delay_seconds"):
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{field} must be positive and finite")
        for field in ("max_per_day", "max_interventions"):
            if type(getattr(self, field)) is not int or getattr(self, field) <= 0:
                raise ValueError(f"{field} must be a positive integer")
        for field in ("start_hour", "end_hour"):
            if type(getattr(self, field)) is not int or not 0 <= getattr(self, field) <= 23:
                raise ValueError(f"{field} must be between 0 and 23")
        if self.start_hour == self.end_hour:
            raise ValueError("Start and end hours must differ")
        ZoneInfo(self.timezone)

    def local_date(self, timestamp):
        return datetime.fromtimestamp(timestamp, ZoneInfo(self.timezone)).date().isoformat()

    def allows_start(self, timestamp):
        hour = datetime.fromtimestamp(timestamp, ZoneInfo(self.timezone)).hour
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        flag = env.get("COORDINATOR_PROACTIVE_ENABLED", "1").strip().lower()
        if flag not in ("1", "0", "true", "false", "yes", "no"):
            raise ValueError("COORDINATOR_PROACTIVE_ENABLED must be a boolean")
        return cls(
            proactive_enabled=flag in ("1", "true", "yes"),
            idle_seconds=float(env.get("COORDINATOR_IDLE_SECONDS", "1800")),
            cooldown_seconds=float(env.get("COORDINATOR_PROACTIVE_COOLDOWN_SECONDS", "10800")),
            max_per_day=int(env.get("COORDINATOR_PROACTIVE_MAX_PER_DAY", "3")),
            recheck_seconds=float(env.get("COORDINATOR_PROACTIVE_RECHECK_SECONDS", "1800")),
            max_interventions=int(env.get("COORDINATOR_MAX_BOT_INTERVENTIONS", "6")),
            turn_delay_seconds=float(
                env.get(
                    "COORDINATOR_BOT_TURN_DELAY_SECONDS", env.get("COORDINATOR_REPLY_DELAY", "8")
                )
            ),
            timezone=env.get("COORDINATOR_TIMEZONE", "America/Lima"),
            start_hour=int(env.get("COORDINATOR_PROACTIVE_START_HOUR", "9")),
            end_hour=int(env.get("COORDINATOR_PROACTIVE_END_HOUR", "23")),
        )
