"""Comando !regalo: Airi juzga el regalo y ajusta la afinidad."""

import time

import aiohttp

from airi.discord_bot.persistence import async_state_transaction
from airi.domain.constants import GIFT_COOLDOWN, MAX_RECENT_GIFTS
from airi.domain.gifts import GIFTS, gift_effect
from airi.domain.texts import gift_reaction


async def handle(ctx, message):
    content = message.content.strip()
    state = ctx.state
    parts = content.split(maxsplit=1)
    opciones = ", ".join(sorted(GIFTS))
    if len(parts) == 1:
        await message.reply(
            f"¿Qué me regalas? Opciones: {opciones}.", mention_author=False
        )
        return
    item = parts[1].strip().lower()
    if item not in GIFTS:
        await message.reply(
            f"No conozco ese regalo... Prueba con: {opciones}.",
            mention_author=False,
        )
        return

    uid = message.author.id
    owner_id, _owner_session = ctx.busy_date_owner(exclude_id=uid)
    if owner_id is not None:
        await ctx.notify_busy(message.channel, message.author)
        return

    entry = state.affinity_entry(uid)
    now = time.time()
    last_gift = float(entry.get("last_gift", 0.0) or 0.0)
    if now - last_gift < GIFT_COOLDOWN:
        await message.reply(
            "Airi ya ha recibido un regalo tuyo hoy... guarda el siguiente "
            "para mañana~",
            mention_author=False,
        )
        return

    recent = entry.get("gifts") or []
    effect = 0
    reaction = None
    gift_reason = None
    session_timeout = aiohttp.ClientTimeout(total=ctx.request_timeout)
    async with aiohttp.ClientSession(timeout=session_timeout) as session:
        judged = await ctx.judge_gift(session, item, message.author, recent)
        if judged is None:
            effect = gift_effect(item, state.world.get("preferences"), recent)
            reaction = gift_reaction(item, effect)
        else:
            reaction, effect, gift_reason = judged
            if not reaction:
                reaction = gift_reaction(item, effect)
        name = state.display_name(uid)
        if gift_reason and gift_reason.lower() not in ("none", "ninguno", "null"):
            gift_note = f"{name} me ha regalado {item}. {gift_reason}"
        elif effect > 0:
            gift_note = f"{name} me ha regalado {item} y me ha hecho mucha ilusión."
        elif effect < 0:
            gift_note = (
                f"{name} me ha regalado {item}... no era lo que "
                "más me apetecía, pero se ha molestado por mí."
            )
        else:
            gift_note = (
                f"{name} me ha regalado {item}. Es el detalle lo que cuenta."
            )
        async with async_state_transaction(ctx):
            state.apply_affinity(uid, effect, now=now)
            entry["last_gift"] = now
            entry["gifts"] = ([item] + [g for g in recent if g != item])[
                :MAX_RECENT_GIFTS
            ]
            state.save_affinity()
            ctx.log_diary_event("gift", message.author, gift_note)
        await message.channel.send(reaction)
