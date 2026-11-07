"""Comandos de identidad: `!identidad-<id del personaje>` y `!yo`."""

from __future__ import annotations

import time

import aiohttp

from airi.discord_bot import embeds
from airi.domain.mood import render_mood_history
from airi.domain.self_model import (
    render_self_history,
    render_self_narrative,
    revert_self_update,
)
from airi.domain.self_notes import recent_notes
from airi.persona import character_name, current_persona
from airi.services.self_service import SelfService


async def handle_yo(ctx, message):
    """Muestra quién es Airi ahora, sin notas que puedan nombrar a usuarios.

    Las notas privadas de autodescubrimiento siguen alimentando su prompt,
    pero el comando público muestra solo la identidad tipada.
    """
    model = ctx.state.self_model()
    text = render_self_narrative(
        model,
        notes=[],
        preferences=ctx.state.world.get("preferences"),
        mood=ctx.state.world.get("mood"),
    )
    await message.channel.send(embed=embeds.system_embed(text))


async def handle_yo_historia(ctx, message):
    """Muestra el historial de cambios de identidad."""
    model = ctx.state.self_model()
    await message.channel.send(
        embed=embeds.system_embed(render_self_history(model))
    )


async def handle_descubrimientos(ctx, message):
    """Muestra al dueño las notas privadas de autodescubrimiento."""
    if ctx.owner_id and message.author.id != ctx.owner_id:
        await message.reply(
            embed=embeds.system_embed(
                f"Solo el dueño del canal puede consultar los descubrimientos privados de {character_name()}."
            ),
            mention_author=False,
        )
        return

    notes = recent_notes(ctx.state.self_notes(), limit=20)
    if not notes:
        text = "Aún no tengo descubrimientos guardados sobre mí."
    else:
        text = "**Mis descubrimientos recientes:**\n" + "\n".join(
            f"• {note}" for note in notes
        )
    await message.reply(
        embed=embeds.system_embed(text),
        mention_author=False,
    )


async def handle_animo(ctx, message):
    """Muestra el ánimo actual y su evolución reciente."""
    owner_only_cause = bool(
        ctx.owner_id and message.author.id == ctx.owner_id
    )
    text = render_mood_history(
        ctx.state.world, include_cause=owner_only_cause
    )
    await message.channel.send(embed=embeds.system_embed(text))


def reflection_notice(outcome):
    if outcome is None:
        return (
            "Ehh... no he conseguido mirarme por dentro ahora mismo. "
            "¿Lo intentamos otra vez en un momentito?"
        )
    if not outcome.ran:
        return (
            "Aún no me toca una pausa para reflexionar (o el modelo no está "
            "disponible). Prueba más tarde."
        )
    if not outcome.changed:
        return (
            "Me he quedado callada pensando en quién soy... pero esta vez no "
            "he cambiado nada de mí."
        )
    lines = [f"*{character_name()} se ha mirado por dentro y algo ha cambiado:*"]
    if outcome.discovery:
        lines.append(f"• **Descubrimiento:** {outcome.discovery}")
    if outcome.self_entry:
        entry = outcome.self_entry
        lines.append(
            f"• **Cambio:** `{entry['key']}` {entry['from']} → {entry['to']}"
        )
    lines.append(f"Escribe `!identidad-{current_persona().id}` para verme completa.")
    return "\n".join(lines)


async def handle_descubrir(ctx, message):
    """Fuerza una reflexión introspectiva. Solo el dueño."""
    if ctx.owner_id and message.author.id != ctx.owner_id:
        await message.reply(
            embed=embeds.system_embed(
                "Solo el dueño del canal puede forzar el autodescubrimiento."
            ),
            mention_author=False,
        )
        return
    outcome = None
    try:
        timeout = aiohttp.ClientTimeout(total=ctx.request_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            from airi.adapters.http_llm import build_llm

            llm = build_llm(
                session, timeout=ctx.request_timeout, base_url=ctx.llm_base_url
            )
            service = SelfService(
                llm=llm,
                state=ctx.state,
                clock=time.time,
                lock=getattr(ctx, "commit_lock", None),
                persistence=getattr(ctx, "persistence", None),
            )
            outcome = await service.reflect(
                message.author.id, now=time.time(), force=True
            )
    except Exception:
        pass
    await message.reply(
        embed=embeds.system_embed(reflection_notice(outcome)),
        mention_author=False,
    )


async def handle_yo_revertir(ctx, message):
    """Revierte un cambio del historial. Solo el dueño puede hacerlo."""
    if ctx.owner_id and message.author.id != ctx.owner_id:
        await message.reply(
            embed=embeds.system_embed(
                "Solo el dueño del canal puede revertir cambios de identidad."
            ),
            mention_author=False,
        )
        return
    parts = message.content.split()
    try:
        index = int(parts[2])
    except (IndexError, ValueError):
        await message.reply(
            embed=embeds.system_embed("El número debe ser entero."),
            mention_author=False,
        )
        return
    state = ctx.state
    entry = revert_self_update(state.self_model(), index, now=time.time())
    if not entry:
        await message.reply(
            embed=embeds.system_embed(
                "No encontré ese cambio o no se puede revertir."
            ),
            mention_author=False,
        )
        return
    state.save_identity()
    await message.reply(
        embed=embeds.system_embed(
            f"Revertido cambio nº {index}: {entry['key']} → {entry['from']}."
        ),
        mention_author=False,
    )
