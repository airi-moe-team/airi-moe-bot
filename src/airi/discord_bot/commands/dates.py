"""Comando !cita: propone escenas y abre el selector de cita."""

import logging
import time

import aiohttp

from airi.discord_bot import embeds
from airi.discord_bot.views import date as date_views
from airi.domain.affinity import is_winner
from airi.domain.constants import DATE_COOLDOWN
from airi.persona import character_name

log = logging.getLogger(__name__)


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
            f"Ehh... lo siento, pero ya tengo novio: "
            f"**{state.display_name(world['winner_id'])}**. "
            "Podemos quedar como amigos, ¿vale?",
            mention_author=False,
        )
        return

    entry = state.affinity_entry(uid)
    now = time.time()
    last_date = float(entry.get("last_date", 0.0) or 0.0)
    if now - last_date < DATE_COOLDOWN:
        remaining = int((DATE_COOLDOWN - (now - last_date)) // 3600)
        await message.reply(
            f"{character_name()} ya ha salido contigo hace poco... dale un respiro "
            f"(en ~{remaining} h).",
            mention_author=False,
        )
        return

    if str(uid) in state.dates:
        await message.reply(
            "¡Ya estáis en una cita! *se ríe* concéntrate en el momento~",
            mention_author=False,
        )
        return

    timeout = aiohttp.ClientTimeout(total=ctx.request_timeout)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with message.channel.typing():
            try:
                decision = await ctx.evaluate_date_invitation(session, message.author)
            except Exception:
                log.exception("No se pudo evaluar la invitación a cita")
                decision = None

            if (
                decision is None
                or getattr(decision, "decision", None) not in ("accept", "reject")
                or not str(getattr(decision, "reply", "") or "").strip()
            ):
                await message.reply(
                    "Ahora mismo no consigo aclararme... ¿me lo preguntas otra vez luego?",
                    mention_author=False,
                )
                return

            if decision.decision == "reject":
                await message.reply(decision.reply, mention_author=False)
                return

            scenes = await ctx.propose_scenes(session, message.author)

    embed = embeds.scene_select_embed(date_views.DATE_EMBED_COLOR)
    view = date_views.SceneSelectView(
        uid, scenes, ctx.handle_scene_choice, timeout=120
    )
    await message.channel.send(content=decision.reply, embed=embed, view=view)
