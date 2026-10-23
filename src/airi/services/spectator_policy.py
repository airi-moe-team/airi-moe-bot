"""Política del modo espectador: cooldowns y evaluación del evento.

Separa la mecánica social (frecuencia, tirada) del dominio puro. El cooldown
solo se arma cuando la intervención espontánea se publica con éxito; la tirada
fallida NO lo consume, de modo que el siguiente mensaje pueda despertar a Airi.
"""

from __future__ import annotations

import random
import time

from airi.domain.spectator import decide_activation


class ActivitiesCooldown:
    """Registro de cooldown por (canal, autor) con reloj inyectable."""

    def __init__(self, *, cooldown_seconds=300, clock=None):
        self.cooldown_seconds = int(cooldown_seconds)
        self._clock = clock or time.time
        self._armed_at = {}

    def _now(self):
        return float(self._clock())

    def can_fire(self, channel_id, author_id, *, now=None):
        """True si el cooldown no está activo (o la clave nunca se armó)."""
        key = (str(channel_id), str(author_id))
        armed = self._armed_at.get(key)
        at = float(now) if now is not None else self._now()
        if armed is None:
            return True
        return (at - armed) >= self.cooldown_seconds

    def arm(self, channel_id, author_id, *, now=None):
        """Arma el cooldown tras publicar una intervención espontánea."""
        key = (str(channel_id), str(author_id))
        at = float(now) if now is not None else self._now()
        self._armed_at[key] = at

    def next_roll(self):
        """Tirada local previa al LLM (inyectable en tests)."""
        return random.random()


def evaluate_event(
    *,
    policy,
    gate,
    channel_id,
    author_id,
    mention,
    topic,
    affinity,
):
    """Compone señales + cooldown + tirada en una decisión de despertar.

    - La mención/respuesta garantizada ignora el cooldown (prioridad social).
    - Las señales espontáneas exigen cooldown libre y tirada favorable.
    """
    decision = decide_activation(
        mention=mention,
        topic=topic,
        affinity=affinity,
        roll=gate.next_roll() if gate is not None else 0.0,
        policy=policy,
    )
    if not decision.proceed or decision.guaranteed or gate is None:
        return decision
    if gate.can_fire(channel_id=channel_id, author_id=author_id):
        return decision
    return decide_activation(
        mention=False,
        topic=False,
        affinity=False,
        roll=decision.roll,
        policy=policy,
    )


__all__ = ["ActivitiesCooldown", "evaluate_event"]
