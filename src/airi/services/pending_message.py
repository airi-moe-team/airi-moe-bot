"""Seguimiento de mensajes pendientes y de mensajes respondidos por canal.

Este módulo gestiona la determinación del "último mensaje humano pendiente "
para el arranque: no basta con el último mensaje humano, hay que comprobar
si ya fue atendido por Airi.

Invariantes:
- I2: Un mensaje respondido no vuelve a ser candidato tras reinicio.
- I3: Ningún mensaje se marca atendido prematuramente (solo al publicar).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Optional


class PendingMessageError(RuntimeError):
    """Error base del tracker de mensajes pendientes."""


class PendingMessageTracker:
    """Registro de mensajes respondidos y búsqueda de pendientes.

    El seguimiento es por canal. Los IDs de mensajes respondidos se
    persisten en el estado del bot (state.world['answered_message_ids'])
    para que sobrevivan a los reinicios.
    """

    def __init__(self, state=None, clock: Optional[callable] = None):
        self._answered: dict[str, set[str]] = {}
        self._state = state  # referencia opcional al agregado de estado
        self._clock = clock or time.time
        if state is not None:
            self._load_from_state()

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------

    def _answered_key(self, channel_id: str) -> str:
        return str(channel_id)

    def _load_from_state(self) -> None:
        """Carga los IDs respondidos desde el agregado de estado (si aplica)."""
        if self._state is None:
            return
        try:
            world = self._state.world if hasattr(self._state, 'world') else None
            if not isinstance(world, dict):
                return
            raw = world.get('answered_message_ids')
            if not isinstance(raw, dict):
                return
            for channel_id, ids in raw.items():
                if isinstance(ids, list):
                    self._answered[str(channel_id)] = {str(i) for i in ids if i}
        except Exception:
            # Fallback seguro: no corromper el flujo por un estado corrupto.
            self._answered = {}

    def _save_to_state(self, state) -> None:
        """Persiste los IDs respondidos en el agregado de estado."""
        if state is None:
            return
        world = getattr(state, 'world', None)
        if not isinstance(world, dict):
            return
        world['answered_message_ids'] = {
            k: sorted(v) for k, v in self._answered.items()
        }
        try:
            save = getattr(state, 'save_world', None)
            if callable(save):
                save()
        except Exception:
            # Mejor esfuerzo: el fallo de disco no debe abortar el turno.
            pass

    # ------------------------------------------------------------------
    # Regime answered
    # ------------------------------------------------------------------

    def mark_answered(self, channel_id: str, message_id: str) -> None:
        """Registrar que Airi respondió a ``message_id`` en ``channel_id``.

        Solo se debe llamar tras la publicación exitosa del mensaje.
        """
        self.mark_answered_many(channel_id, [message_id])

    def mark_answered_many(self, channel_id: str, message_ids: Iterable[Any]) -> None:
        """Registrar varios mensajes atendidos en una sola escritura.

        Un turno puede cubrir el mensaje que lo disparó, los mensajes
        agrupados por el debounce y los del snapshot pasivo. Todos deben
        quedar marcados para que un reinicio no los reviva (invariante I2).
        """
        key = str(channel_id)
        ids = {str(message_id) for message_id in message_ids if message_id}
        if not ids:
            return
        self._answered.setdefault(key, set()).update(ids)
        # Persistencia síncrona (mejor esfuerzo). Si no hay estado, solo en memoria.
        if self._state is not None:
            self._save_to_state(self._state)

    def is_answered(self, channel_id: str, message_id: str) -> bool:
        """True si ``message_id`` ya fue respondido en ``channel_id``."""
        return str(message_id) in self._answered.get(str(channel_id), set())

    def pending_ids(self, channel_id: str) -> set[str]:
        """IDs de mensajes pendientes en ``channel_id`` (sin cargar el historial)."""
        return self._answered.get(str(channel_id), set())

    # ------------------------------------------------------------------
    # Búsqueda de mensaje pendiente
    # ------------------------------------------------------------------

    def find_pending_message(
        self,
        history: Iterable[Any],
        bot_id: Optional[int] = None,
        *,
        max_age: Optional[float] = None,
        command_prefix: str = "!",
        now: Optional[float] = None,
    ) -> Any:
        """Devuelve el último mensaje humano pendiente, o None.

        Criterios:
        - Es un mensaje de usuario (no bot, no Airi).
        - No es un comando.
        - Tiene contenido o adjuntos.
        - No está en el registro de respondidos.
        - La antigüedad (si se proporciona) está dentro de max_age.
        - Está después de la última respuesta textual de Airi: una intervención
          suya cierra el hilo y nada anterior vuelve a considerarse pendiente.

        ``history`` debe estar ordenado de más reciente a más antiguo
        (conforme a ``channel.history(limit=N)``).
        """
        now = self._clock() if now is None else float(now)
        for entry in history:
            author = getattr(entry, 'author', None)
            if author is None:
                continue
            author_id = getattr(author, 'id', None)
            is_airi = bot_id is not None and author_id == bot_id
            if is_airi or getattr(author, 'bot', False):
                # Cortafuegos temporal: si Airi ya respondió con texto, los
                # mensajes anteriores quedaron cubiertos por esa respuesta.
                if is_airi and (getattr(entry, 'content', '') or '').strip():
                    break
                # Los embeds de sistema (conexión, desconexión, GIF) no cortan
                # la búsqueda: no son una respuesta conversacional.
                continue
            content = (getattr(entry, 'content', '') or '').strip()
            if content.startswith(command_prefix):
                continue
            attachments = getattr(entry, 'attachments', None) or []
            if not content and not attachments:
                continue
            if self.is_answered(self._entry_channel_key(entry), str(getattr(entry, 'id', ''))):
                continue
            created_at = getattr(entry, 'created_at', None)
            if created_at is not None and max_age is not None:
                if now - self._epoch(created_at) > float(max_age):
                    continue
            return entry
        return None

    @staticmethod
    def _entry_channel_key(entry: Any) -> str:
        """Clave de canal estable para objetos tipo mensaje.

        discord.Message expone ``channel.id`` (sin ``channel_id``),
        mientras que los fakes de prueba suelen traer ``channel_id``.
        Se aceptan ambas formas para que la exclusión funcionen igual
        en producción y en pruebas.
        """
        channel_id = getattr(entry, 'channel_id', None)
        if channel_id is None:
            channel = getattr(entry, 'channel', None)
            channel_id = getattr(channel, 'id', None)
        return str(channel_id) if channel_id is not None else ''

    @staticmethod
    def _epoch(value: Any) -> float:
        """Convierte un instante (datetime o epoch) a epoch en segundos."""
        timestamp = getattr(value, 'timestamp', None)
        if timestamp is not None:
            try:
                return float(timestamp())
            except Exception:
                pass
        try:
            return float(value)
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # Estado serializado
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            'answered_message_ids': {
                key: sorted(values) for key, values in self._answered.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'PendingMessageTracker':
        inst = cls()
        if isinstance(data, dict):
            raw = data.get('answered_message_ids')
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(v, list):
                        inst._answered[k] = {str(i) for i in v if i}
        return inst


__all__ = ['PendingMessageTracker', 'PendingMessageError']
