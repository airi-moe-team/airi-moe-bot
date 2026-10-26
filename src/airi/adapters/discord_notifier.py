"""Notificador que envía avisos de sistema como embeds de Discord."""

from __future__ import annotations

from airi.discord_bot.embeds import notice_embed


class DiscordNotifier:
    """Implementa `airi.ports.notifier.Notifier` sobre `discord.abc.Messageable`."""

    def __init__(self, channel):
        self.channel = channel

    async def send(self, content):
        await self.channel.send(embed=notice_embed(content))
