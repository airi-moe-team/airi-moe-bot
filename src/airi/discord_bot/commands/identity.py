"""Comandos de identidad de Airi: `!identidad-airi` (alias `!yo`) y `!descubrir`."""

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
    """Lista resumida del historial de cambios (para `!identidad-airi historia`)."""
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
    """Muestra quién es Airi ahora (`!identidad-airi`, alias `!yo`)."""
    state = ctx.state
    model = state.self_model()
    text = render_self_narrative(model)
    await message.channel.send(embed=embeds.system_embed(text))


async def handle_yo_historia(ctx, message):
    """Muestra el historial de cambios (`!identidad-airi historia`)."""
    state = ctx.state
    model = state.self_model()
    await message.channel.send(embed=embeds.system_embed(render_self_history(model)))


async def handle_yo_revertir(ctx, message):
    """Revierte un cambio del historial (`!identidad-airi revertir <n>`). Solo dueño."""
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


def reflection_notice(outcome):
    """Texto del aviso de `!descubrir` con el resultado REAL de la reflexión.

    `outcome` es un `ReflectionOutcome` de `SelfService.reflect`, o `None` si
    la reflexión ni siquiera pudo ejecutarse (error de red/servicio).
    """
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
    lines = ["*Airi se ha mirado por dentro y algo ha cambiado:*"]
    if outcome.discovery:
        lines.append(f"• **Descubrimiento:** {outcome.discovery}")
    if outcome.self_entry:
        entry = outcome.self_entry
        lines.append(f"• **Cambio:** `{entry['key']}` {entry['from']} → {entry['to']}")
    lines.append("Escribe `!identidad-airi` para verme completa.")
    return "\n".join(lines)


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
    outcome = None
    try:
        import aiohttp

        from airi.adapters.http_llm import build_llm

        timeout = aiohttp.ClientTimeout(total=ctx.request_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            llm = build_llm(
                session, timeout=ctx.request_timeout, base_url=ctx.llama_url
            )
            service = SelfService(llm=llm, state=state, clock=time.time)
            outcome = await service.reflect(message.author.id, now=time.time(), force=True)
    except Exception:
        pass
    await message.reply(
        embed=embeds.system_embed(reflection_notice(outcome)),
        mention_author=False,
    )
