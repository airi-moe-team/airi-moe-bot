"""Notificador que envía avisos de sistema como embeds de Discord."""

from __future__ import annotations

import discord


class DiscordNotifier:
    """Implementa `airi.ports.notifier.Notifier` sobre `discord.abc.Messageable`."""

    def __init__(self, channel):
        self.channel = channel

    async def send(self, content):
        embed = discord.Embed(
            title="💗 Airi",
            description=str(content),
            color=discord.Color(0xFFB6D9),
        )
        await self.channel.send(embed=embed)
