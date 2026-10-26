"""Puerto: notificador de mensajes (abstrae Discord)."""

from __future__ import annotations

from typing import Any, Protocol

from airi.domain.notices import Notice


class Notifier(Protocol):
    """Canal de mensajería."""

    async def send(self, content: Notice | str) -> Any:
        ...
