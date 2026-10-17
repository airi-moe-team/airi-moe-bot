"""Comando !reiniciar-temporada (solo OWNER_ID)."""

from airi.discord_bot import embeds


async def handle(ctx, message):
    state = ctx.state
    if ctx.owner_id and message.author.id != ctx.owner_id:
        await message.reply(
            embed=embeds.system_embed(
                "Solo el dueño del canal puede reiniciar la temporada."
            ),
            mention_author=False,
        )
        return
    state.world["winner_id"] = None
    state.world["relationship_started_at"] = None
    state.world["season"] = int(state.world.get("season", 1) or 1) + 1
    state.save_world()
    for uid, entry in state.affinity.items():
        if str(uid).startswith("_") or not isinstance(entry, dict):
            continue
        entry["points"] = 0
        entry["milestones"] = []
    state.save_affinity()
    # Los contadores de interacción se inyectan al prompt de Airi
    # (`known_users_prompt_section`), lo que sesgaría la nueva temporada hacia
    # quien más habló antes. Se reinician a 0 conservando nombre y fechas.
    for entry in state.users.values():
        if isinstance(entry, dict):
            entry["interactions"] = 0
    state.save_users()
    state.dates.clear()
    state.save_dates()
    state.memories.clear()
    state.save_memories()
    state.histories.clear()
    state.diary.clear()
    state.save_diary()
    await message.channel.send(
        embed=embeds.system_embed(
            "💞 Nueva temporada: el corazón de Airi vuelve a estar libre. "
            "¡Que empiece la conquista!"
        )
    )
