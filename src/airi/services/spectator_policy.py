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
    """Registros de cooldown y handoff por (canal, autor), reloj inyectable."""

    def __init__(self, *, cooldown_seconds=300, handoff_seconds=180, clock=None):
        self.cooldown_seconds = int(cooldown_seconds)
        self.handoff_seconds = int(handoff_seconds)
        self._clock = clock or time.time
        self._armed_at = {}
        self._handoff_until = {}

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

    # ------------------------------------------------------------------
    # Handoff: una respuesta del interlocutor tras una pregunta de Airi
    # bypassa el cooldown una sola vez y solo durante la ventana.
    # ------------------------------------------------------------------

    def arm_handoff(self, channel_id, author_id, *, now=None):
        key = (str(channel_id), str(author_id))
        at = float(now) if now is not None else self._now()
        self._handoff_until[key] = at + self.handoff_seconds

    def has_pending_handoff(self, channel_id, author_id, *, now=None):
        key = (str(channel_id), str(author_id))
        until = self._handoff_until.get(key)
        at = float(now) if now is not None else self._now()
        if until is None:
            return False
        if at <= until:
            return True
        self._handoff_until.pop(key, None)
        return False

    def clear_handoff(self, channel_id, author_id):
        self._handoff_until.pop((str(channel_id), str(author_id)), None)


def evaluate_event(
    *,
    policy,
    gate,
    channel_id,
    author_id,
    mention,
    topic,
    affinity,
    handoff=False,
):
    """Compone señales + cooldown + tirada en una decisión de despertar.

    - La mención directa y el handoff (responder a la pregunta de Airi) son
      garantizados e ignoran el cooldown.
    - Las señales espontáneas exigen cooldown libre y tirada favorable.
    """
    decision = decide_activation(
        mention=mention,
        topic=topic,
        affinity=affinity,
        roll=gate.next_roll() if gate is not None else 0.0,
        policy=policy,
        handoff=handoff,
    )
    if not decision.proceed or decision.guaranteed or gate is None:
        return decision
    if gate.can_fire(channel_id=channel_id, author_id=author_id):
        return decision
    return decide_activation(
        mention=False,
        handoff=False,
        topic=False,
        affinity=False,
        roll=decision.roll,
        policy=policy,
    )


__all__ = ["ActivitiesCooldown", "evaluate_event"]
