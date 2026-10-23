"""Buffer pasivo del modo espectador en memoria volátil (sin disco).

Cada canal tiene una cola FIFO de observaciones. No se toca el estado
persistido: lo que Airi "vio" como espectadora muere al reiniciar y caduca por
TTL. El snapshot es efímero: solo se consume el subconjunto enviado al LLM para
componer la respuesta, y si la publicación falla se conserva lo no consumido
hasta el TTL.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BufferEntry:
    """Una observación de escucha pasiva (sin I/O, sin contenidos sensible)."""

    channel_id: str
    author_id: str
    author_name: str
    content: str
    message_id: str
    ts: float


def _clean_text(value):
    return " ".join(str(value or "").split())


class PassiveBuffer:
    """Observaciones por canal con límite FIFO y descarte por TTL."""

    def __init__(self, *, buffer_max=20, ttl_seconds=1800, clock=0):
        self.buffer_max = int(buffer_max)
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._channels = {}

    def _now(self):
        if callable(self._clock):
            return float(self._clock())
        return float(self._clock or 0.0)

    def _prune(self, channel_id, now):
        entries = self._channels.get(str(channel_id))
        if not entries:
            self._channels.pop(str(channel_id), None)
            return []
        keep = [e for e in entries if (now - e.ts) <= self.ttl_seconds]
        self._channels[str(channel_id)] = keep
        if not keep:
            self._channels.pop(str(channel_id), None)
        return keep

    def append(
        self,
        channel_id,
        author_id,
        author_name,
        content,
        *,
        ts=None,
        message_id="",
    ):
        """Registra un mensaje manteniendo límite FIFO y TTL."""
        channel_id_key = str(channel_id)
        now = self._now() if ts is None else float(ts)
        keep = self._prune(channel_id_key, now)
        entry = BufferEntry(
            channel_id=channel_id_key,
            author_id=str(author_id),
            author_name=str(author_name or ""),
            content=_clean_text(content),
            message_id=str(message_id or ""),
            ts=now,
        )
        if not entry.content:
            return entry
        keep.append(entry)
        # FIFO: si excede el límite se descartan los más antiguos.
        while len(keep) > self.buffer_max:
            keep.pop(0)
        self._channels[channel_id_key] = keep
        return entry

    def snapshot(
        self,
        channel_id,
        *,
        now,
        exclude_ids=frozenset(),
    ):
        """Ventana vigente en orden cronológico, sin las entradas excluidas."""
        text = [entry for entry in self._prune(str(channel_id), now)]
        if exclude_ids:
            excluded = {str(item) for item in exclude_ids}
            text = [entry for entry in text if entry.message_id not in excluded]
        return list(text)

    def mark_consumed(self, channel_id, message_ids):
        """Retira del buffer los mensajes incluidos en el snapshot publicado."""
        consumed = {str(item) for item in message_ids if str(item)}
        if not consumed:
            return
        remaining = [
            entry
            for entry in self._channels.get(str(channel_id), [])
            if entry.message_id not in consumed
        ]
        self._channels[str(channel_id)] = remaining

    def clear(self, channel_id):
        """Vacía el buffer de un canal (reset de conversación/temporada)."""
        self._channels.pop(str(channel_id), None)

    def clear_all(self):
        """Vacía todos los buffers (estructura de temporadas)."""
        self._channels.clear()


__all__ = ["BufferEntry", "PassiveBuffer"]
