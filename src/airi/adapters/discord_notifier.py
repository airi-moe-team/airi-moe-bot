"""Notificador que envía mensajes a un canal de Discord."""

from __future__ import annotations

from airi.discord_bot import embeds


class DiscordNotifier:
    """Implementa `airi.ports.notifier.Notifier` sobre `discord.abc.Messageable`.

    Solo transporta mensajes de sistema (aviso de búsqueda, memoria guardada,
    crisis y cierre de cita), así que se presentan como embed de sistema.
    """

    def __init__(self, channel):
        self.channel = channel

    async def send(self, content):
        await self.channel.send(embed=embeds.system_embed(content))
