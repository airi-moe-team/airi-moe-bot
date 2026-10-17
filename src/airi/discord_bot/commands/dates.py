"""Comando !cita: abre la invitación y pide la escena por texto libre."""

import time

from airi.discord_bot import embeds
from airi.domain.affinity import can_date, entry_points, is_winner
from airi.domain.constants import DATE_COOLDOWN


async def handle(ctx, message):
    uid = message.author.id
    state = ctx.state

    owner_id, owner_session = ctx.busy_date_owner(exclude_id=uid)
    if owner_id is not None:
        await ctx.notify_busy(message.channel, message.author)
        return

    world = state.world
    if world.get("winner_id") and not is_winner(world, uid):
        await message.reply(
            embed=embeds.system_embed(
                f"Ehh... lo siento, pero ya tengo novio: "
                f"**{state.display_name(world['winner_id'])}**. "
                "Podemos quedar como amigos, ¿vale?"
            ),
            mention_author=False,
        )
        return

    entry = state.affinity_entry(uid)
    if not can_date(entry_points(entry)):
        await message.reply(
            embed=embeds.system_embed(
                "Ehh... *se rasca la mejilla* todavía no te conozco lo suficiente "
                "para una cita. Llega a ser mi **amiga** y te diré que sí, ¿vale?"
            ),
            mention_author=False,
        )
        return

    now = time.time()
    last_date = float(entry.get("last_date", 0.0) or 0.0)
    if now - last_date < DATE_COOLDOWN:
        remaining = int((DATE_COOLDOWN - (now - last_date)) // 3600)
        await message.reply(
            embed=embeds.system_embed(
                f"Airi ya ha salido contigo hace poco... dale un respiro "
                f"(en ~{remaining} h)."
            ),
            mention_author=False,
        )
        return

    if str(uid) in state.dates:
        await message.reply(
            embed=embeds.system_embed(
                "¡Ya estáis en una cita! *se ríe* concéntrate en el momento~"
            ),
            mention_author=False,
        )
        return

    # Ya no se proponen planes con botones: Airi pregunta y el jugador
    # responde en su próximo mensaje con la escena que quiera.
    text = ctx.request_scene(uid)
    await message.channel.send(embed=embeds.system_embed(text))
