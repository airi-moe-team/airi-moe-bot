"""Comando !ranking."""

from airi.discord_bot import embeds
from airi.domain.affinity import ranking
from airi.persona import character_name


async def handle(ctx, message):
    state = ctx.state
    rows = ranking(state.affinity, state.users, state.world.get("winner_id"))
    if not rows:
        await message.channel.send(
            "Todavía no hay pretendientes... ¿te atreves a ser el primero?"
        )
        return
    winner = state.world.get("winner_id")
    if winner:
        status = f"💍 {character_name()} ya es novia de **{state.display_name(winner)}**."
    else:
        status = f"💌 {character_name()} sigue soltera: el corazón está libre."
    await message.channel.send(embed=embeds.ranking_embed(rows, status))
