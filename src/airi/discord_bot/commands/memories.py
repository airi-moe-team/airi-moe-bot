"""Comandos !memorias y !olvidar."""

from airi.discord_bot import embeds
from airi.domain import diary as domain_diary
from airi.domain import memories as domain_memories


async def handle_memorias(ctx, message):
    entries = ctx.state.user_memories(message.author.id)
    if entries:
        listing = "\n".join(
            f"{i}. {e.get('text', '')}"
            for i, e in enumerate(entries, start=1)
            if isinstance(e, dict)
        )
    else:
        listing = "Todavía no recuerdo nada especial sobre ti~"
    await message.channel.send(embed=embeds.memories_embed(listing))


async def handle_olvidar(ctx, message):
    state = ctx.state
    uid = message.author.id
    parts = message.content.strip().split(maxsplit=1)
    if len(parts) == 1:
        await message.reply(
            embed=embeds.system_embed(
                "¿Olvidar qué? Escribe `!olvidar <número>` o `!olvidar todo`."
            ),
            mention_author=False,
        )
        return
    arg = parts[1].strip().lower()
    if arg == "todo":
        if domain_memories.forget_memory(state.memories, uid):
            state.save_memories()
        removed = domain_diary.purge_user_diary(state.diary, uid)
        if removed:
            state.save_diary()
        await message.reply(
            embed=embeds.system_embed(
                "Listo... ¡olvidado todo! (memorias y diario) Empezamos de cero~"
            ),
            mention_author=False,
        )
        return
    entries = state.user_memories(uid)
    if not entries:
        await message.reply(
            embed=embeds.system_embed("No tengo memorias sobre ti todavía."),
            mention_author=False,
        )
        return
    if arg.isdigit() and domain_memories.forget_memory(state.memories, uid, int(arg)):
        state.save_memories()
        await message.reply(
            embed=embeds.system_embed(f"Olvidado: memoria #{arg}. Ya no la recuerdo~"),
            mention_author=False,
        )
        return
    await message.reply(
        embed=embeds.system_embed(
            f"Número no válido. Usa `!memorias` para ver la lista (1-{len(entries)})."
        ),
        mention_author=False,
    )
