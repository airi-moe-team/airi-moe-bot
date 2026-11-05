"""Registro volátil por canal del ciclo de vida conversacional (espectador/activa).

Este módulo es puro respecto a Discord: no crea tareas asyncio ni conoce el
cliente. Solo mantiene el estado efímero por canal y las invariantes de
transición; los temporizadores y la publicación viven en la capa Discord.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class ConversationState(Enum):
    """Estados del ciclo de vida conversacional por canal."""

    SPECTATING = "spectating"
    WAKING = "waking"
    ACTIVE = "active"
    RETIRING = "retiring"


@dataclass
class ChannelSession:
    """Estado efímero de un canal. No se persiste ni se serializa a disco."""

    state: ConversationState = ConversationState.SPECTATING
    generation: int = 0
    last_human_activity: Optional[float] = None
    last_proactive_attempt: Optional[float] = None
    active_since: Optional[float] = None
    turn_in_progress: bool = False


class SpectatorSessionRegistry:
    """Dueño del estado de ciclo de vida por canal (volátil, en memoria)."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        cooldown=None,
        active_idle_seconds: float = 300.0,
        proactive_idle_seconds: float = 21600.0,
    ):
        self._clock = clock or time.monotonic
        self._cooldown = cooldown
        self._active_idle_seconds = float(active_idle_seconds)
        self._proactive_idle_seconds = float(proactive_idle_seconds)
        self._sessions: dict[str, ChannelSession] = {}

    def _now(self) -> float:
        return float(self._clock())

    def _session(self, channel_id) -> ChannelSession:
        key = str(channel_id)
        if key not in self._sessions:
            self._sessions[key] = ChannelSession()
        return self._sessions[key]

    def mark_turn_started(self, channel_id) -> None:
        """Marcar que hay un turno en progreso (invariante I1)."""
        s = self._session(channel_id)
        s.turn_in_progress = True

    def mark_turn_finished(self, channel_id) -> None:
        """Marcar que el turno terminó (invariante I1)."""
        s = self._session(channel_id)
        s.turn_in_progress = False

    def state(self, channel_id) -> ConversationState:
        return self._session(channel_id).state

    def session(self, channel_id) -> ChannelSession:
        """Vista (copia superficial) del estado del canal."""
        s = self._sessions.get(str(channel_id))
        if s is None:
            return ChannelSession()
        return ChannelSession(
            state=s.state,
            generation=s.generation,
            last_human_activity=s.last_human_activity,
            last_proactive_attempt=s.last_proactive_attempt,
            active_since=s.active_since,
        )

    # ------------------------------------------------------------------
    # Actividad humana
    # ------------------------------------------------------------------

    def record_human_activity(self, channel_id, now=None) -> int:
        """Registra actividad humana y devuelve la nueva generación.

        Durante retirada, un mensaje humano saca el canal de ese estado
        transitorio hacia la espectadora. Los demás estados se conservan.
        """
        at = self._now() if now is None else float(now)
        s = self._session(channel_id)
        if s.state == ConversationState.RETIRING:
            s.state = ConversationState.SPECTATING
        s.last_human_activity = at
        s.generation += 1
        return s.generation

    # ------------------------------------------------------------------
    # Despertar
    # ------------------------------------------------------------------

    def begin_waking(self, channel_id, expected_generation: int) -> bool:
        """Transición compare-and-set Espectadora -> Despertando.

        Devuelve True si se abrió el despertar. Cualquier otra combinación
        de estado/generación devuelve False sin mutar.
        """
        s = self._sessions.get(str(channel_id))
        if s is None:
            return False
        if s.state != ConversationState.SPECTATING:
            return False
        if s.generation != int(expected_generation):
            return False
        s.state = ConversationState.WAKING
        s.generation += 1
        return True

    def finish_waking(
        self, channel_id, *, published: bool, stay_active: bool
    ) -> ConversationState:
        """Cierra un despertar.

        Regla dura del dominio: la sesión solo se abre si hubo texto
        publicado. `stay_active` es irrelevante cuando no se publicó texto:
        el despertar se aborta, rearmando el cooldown de espectador por parte
        del llamador y marcando la captura como consumida. En caso de aborto
        el estado vuelve a Espectadora.
        """
        s = self._sessions.get(str(channel_id))
        if s is None or s.state != ConversationState.WAKING:
            return s.state if s is not None else ConversationState.SPECTATING
        if published and bool(stay_active):
            s.state = ConversationState.ACTIVE
            s.active_since = s.last_human_activity or self._now()
            return s.state
        # Aborto (silencio, salida inválida o fallo de publicación).
        s.state = ConversationState.SPECTATING
        return s.state

    # ------------------------------------------------------------------
    # Turno activo
    # ------------------------------------------------------------------

    def enter_active(self, channel_id, *, now=None) -> ConversationState:
        """Fuerza el paso a Activa (arranque de proceso o conexión).

        Refresca ``last_human_activity`` para que la ventana de inactividad
        empiece a contar desde este momento, aunque el canal ya estuviera en
        Activa. Conserva ``active_since`` original si ya había una sesión.
        """
        s = self._session(channel_id)
        at = self._now() if now is None else float(now)
        if s.state != ConversationState.ACTIVE or s.active_since is None:
            s.active_since = at
        s.state = ConversationState.ACTIVE
        s.last_human_activity = at
        s.generation += 1
        return s.state

    def finish_active_turn(
        self, channel_id, *, stay_active: bool, published: bool, silent: bool = False
    ) -> ConversationState:
        """Cierra un turno activo.

        Si se pide permanecer y (hubo publicación exitosa o fue silencio
        deliberado), conserva Activa. En otro caso ejecuta la retirada.
        """
        s = self._sessions.get(str(channel_id))
        if s is None or s.state != ConversationState.ACTIVE:
            return s.state if s is not None else ConversationState.SPECTATING
        if bool(stay_active) and (bool(published) or bool(silent)):
            return s.state
        s.state = ConversationState.RETIRING
        s.state = ConversationState.SPECTATING
        s.active_since = None
        return s.state

    # ------------------------------------------------------------------
    # Temporizadores
    # ------------------------------------------------------------------

    def retire_if_idle(
        self, channel_id, expected_generation: int, now, timeout: float
    ) -> bool:
        """Retira por inactividad si estado/generación/plazo siguen vigentes.

        Devuelve True si se retiró. Un timeout <= 0 deshabilita la operación.
        """
        s = self._sessions.get(str(channel_id))
        if s is None or s.state != ConversationState.ACTIVE:
            return False
        if timeout is None or float(timeout) <= 0:
            return False
        if s.generation != int(expected_generation):
            return False
        at = float(now)
        if s.last_human_activity is None:
            return False
        if (at - s.last_human_activity) < float(timeout):
            return False
        s.state = ConversationState.RETIRING
        s.state = ConversationState.SPECTATING
        s.active_since = None
        return True

    def should_fire_proactive(self, channel_id, now) -> bool:
        """True si puede intentarse un despertar proactivo.

        Invariants aplicados:
        - I4/I6: No dispara si ya hay un turno en curso (turn_in_progress).
        - Solo en SPECTATING, con inactividad suficiente y sin actividad
          posterior que invalide el disparo.
        """
        s = self._sessions.get(str(channel_id))
        if s is None or s.state != ConversationState.SPECTATING:
            return False
        if self._proactive_idle_seconds <= 0:
            return False
        if s.turn_in_progress:
            return False
        if s.last_human_activity is None:
            return False
        at = float(now)
        if (at - s.last_human_activity) < self._proactive_idle_seconds:
            return False
        if (
            s.last_proactive_attempt is not None
            and not (s.last_human_activity > s.last_proactive_attempt)
        ):
            return False
        s.last_proactive_attempt = at
        return True

    # ------------------------------------------------------------------
    # Limpieza
    # ------------------------------------------------------------------

    def clear(self, channel_id) -> None:
        self._sessions.pop(str(channel_id), None)

    def clear_all(self) -> None:
        self._sessions.clear()

    # ------------------------------------------------------------------
    # Acceso a configuración (para la capa Discord)
    # ------------------------------------------------------------------

    @property
    def active_idle_seconds(self) -> float:
        return self._active_idle_seconds

    @property
    def proactive_idle_seconds(self) -> float:
        return self._proactive_idle_seconds


__all__ = [
    "ChannelSession",
    "ConversationState",
    "SpectatorSessionRegistry",
]
