"""Comando !diario."""

import time

import discord

from airi.discord_bot import embeds
from airi.domain.constants import DIARY_VIEW_LIMIT
from airi.domain.diary import (
    diary_for_user,
    diary_kind_label,
    format_relative_time,
    recent_diary,
)


async def handle(ctx, message):
    now = time.time()
    requested_all = (
        len(str(getattr(message, "content", "")).split()) > 1
        and str(message.content).split()[1].lower() in ("todos", "todo")
    )
    is_owner = bool(
        getattr(ctx, "owner_id", None)
        and int(message.author.id) == int(ctx.owner_id)
    )
    if requested_all and is_owner:
        if getattr(message, "guild", None) is not None:
            await message.channel.send(
                embed=embeds.system_embed(
                    "Por privacidad, la vista completa del diario solo se envía "
                    "por mensaje privado. Envíame `!diario todos` por DM."
                )
            )
            return
        entries = recent_diary(ctx.state.diary, limit=DIARY_VIEW_LIMIT)
        destination = message.author
        footer = "Vista completa del diario · mensaje privado"
    else:
        # En canales públicos cada persona ve exclusivamente lo que Airi
        # registró sobre su relación con ella.
        entries = diary_for_user(
            ctx.state.diary, message.author.id, limit=DIARY_VIEW_LIMIT
        )
        destination = message.channel
        footer = "Recuerdos de Airi relacionados contigo"
    if entries:
        listing = "\n".join(
            f"**{format_relative_time(e.get('ts'), now)} · "
            f"{diary_kind_label(e.get('kind'))}** · {e.get('text', '')}"
            for e in entries
        )[:4000]
    else:
        listing = "Airi todavía no tiene recuerdos guardados sobre ti~"
    try:
        await destination.send(embed=embeds.diary_embed(listing, footer=footer))
    except discord.Forbidden:
        # El DM puede estar cerrado; nunca degradar una vista completa a un
        # mensaje público del canal.
        await message.channel.send(
            embed=embeds.system_embed(
                "No pude enviarte el diario por privado. Revisa tus ajustes de DM."
            )
        )
