"""Comandos !afinidad y !relacion."""

import time

from airi.discord_bot import embeds
from airi.domain.affinity import affinity_summary, entry_points, is_winner
from airi.persona import character_name


def _summary(ctx, user_id):
    entry = ctx.state.affinity_entry(user_id)
    return affinity_summary(entry_points(entry))


async def handle_afinidad(ctx, message):
    points, level_name, progress = _summary(ctx, message.author.id)
    await message.channel.send(
        embed=embeds.affinity_embed(message.author, points, level_name, progress)
    )


async def handle_relacion(ctx, message):
    uid = message.author.id
    world = ctx.state.world
    points, level_name, progress = _summary(ctx, uid)
    if is_winner(world, uid):
        started = world.get("relationship_started_at")
        days = (
            max(1, int((time.time() - float(started)) // 86400) + 1)
            if started
            else 1
        )
        estado = f"💍 ¡Eres su novio! Lleváis **{days} día(s)** juntos."
    elif world.get("winner_id"):
        estado = (
            f"💔 {character_name()} ya es novia de **{ctx.state.display_name(world['winner_id'])}**. "
            "Solo puedes ser su amigo."
        )
    else:
        estado = f"💌 {character_name()} está soltera. Sigue conquistándola para ganar la temporada."
    await message.channel.send(
        embed=embeds.relation_embed(message.author, estado, points, level_name, progress)
    )
