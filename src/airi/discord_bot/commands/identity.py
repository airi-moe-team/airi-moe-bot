"""Comandos de identidad de Airi: `!yo` y `!descubrir`."""

from __future__ import annotations

import time

from airi.discord_bot import embeds
from airi.domain.self_model import (
    render_self_narrative,
    revert_self_update,
)
from airi.services.self_service import SelfService


def _fmt_ts(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts) or 0.0))
    except Exception:
        return "desconocido"


def render_self_history(model):
    """Lista resumida del historial de cambios (para `!yo historia`)."""
    lines = []
    history = list(model.get("history") or [])
    for i, entry in enumerate(history, start=1):
        ts = entry.get("ts", 0.0)
        key = entry.get("key", "")
        op = entry.get("op", "")
        frm = entry.get("from")
        to = entry.get("to")
        reason = entry.get("reason", "")
        lines.append(
            f"{i}. {_fmt_ts(ts)} — {key} ({op}): {frm} → {to} — {reason}"
        )
    if not lines:
        return "Airi no ha cambiado nada de su forma de ser todavía."
    return "\n".join(lines[-10:])


async def handle_yo(ctx, message):
    """Muestra quién es Airi ahora (`!yo`)."""
    state = ctx.state
    model = state.self_model()
    text = render_self_narrative(model)
    await message.channel.send(embed=embeds.system_embed(text))


async def handle_yo_historia(ctx, message):
    """Muestra el historial de cambios (`!yo historia`)."""
    state = ctx.state
    model = state.self_model()
    await message.channel.send(embed=embeds.system_embed(render_self_history(model)))


async def handle_yo_revertir(ctx, message):
    """Revierte un cambio del historial (`!yo revertir <n>`). Solo dueño."""
    if ctx.owner_id and message.author.id != ctx.owner_id:
        await message.reply(
            embed=embeds.system_embed(
                "Solo el dueño del canal puede revertir cambios de identidad."
            ),
            mention_author=False,
        )
        return
    parts = message.content.split()
    idx_token = parts[2] if len(parts) > 2 else ""
    try:
        index = int(idx_token)
    except ValueError:
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
    state.save_world()
    await message.reply(
        embed=embeds.system_embed(
            f"Revertido cambio nº {index}: {entry['key']} → {entry['from']}."
        ),
        mention_author=False,
    )


async def handle_descubrir(ctx, message):
    """Fuerza una reflexión introspectiva (`!descubrir`). Solo dueño."""
    if ctx.owner_id and message.author.id != ctx.owner_id:
        await message.reply(
            embed=embeds.system_embed(
                "Solo el dueño del canal puede forzar el autodescubrimiento."
            ),
            mention_author=False,
        )
        return
    state = ctx.state
    try:
        import aiohttp
        from airi.adapters.http_llm import HttpLlmClient

        timeout = aiohttp.ClientTimeout(total=ctx.request_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            llm = HttpLlmClient(ctx.llama_url, session, timeout=ctx.request_timeout)
            service = SelfService(llm=llm, state=state, clock=time.time)
            await service.reflect(message.author.id, now=time.time(), force=True)
    except Exception:
        pass
    await message.reply(
        embed=embeds.system_embed("Airi ha hecho una pausa para mirarse por dentro..."),
        mention_author=False,
    )
