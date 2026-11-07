"""Comando !debug (solo OWNER_ID): inspecciona las trazas de turnos.

Uso:
- `!debug ultimo [n]` — resumen de los últimos `n` eventos del TraceStore
  (por defecto 1; máximo 20).
- `!debug id <cid>` — envía el JSON del evento con ese `correlation_id`
  (busca primero en el ring y, si no, en el directorio de trazas).
- `!debug errores` — lista los eventos recientes con errores.
- `!debug clear` — vacía el ring de eventos en memoria (no toca el disco).
- `!debug turno` — resumen de tu último turno (compatibilidad).
- `!debug trace` — JSON crudo de tu último turno (compatibilidad).
"""

from __future__ import annotations

import io
import json

import discord

from airi.observability.trace import TurnTrace
from airi.observability.trace_store import load_events_from_dir
from airi.persona import character_name

MAX_LIST = 20
MAX_ERRORS = 10

DEBUG_USAGE = (
    "Uso:\n"
    "• `!debug ultimo [n]` — resumen de los últimos `n` eventos (def. 1).\n"
    "• `!debug id <cid>` — JSON del evento con ese correlation_id.\n"
    "• `!debug errores` — eventos recientes con errores.\n"
    "• `!debug clear` — vacía el ring de eventos en memoria.\n"
    "• `!debug estado` — diagnóstico seguro del almacén.\n"
    "• `!debug turno` — resumen de tu último turno.\n"
    "• `!debug trace` — JSON de tu último turno."
)


def _summarize(trace):
    # Fuera de una cita, `date_decision` es un centinela del contrato JSON
    # ("continue"); mostrarlo como decisión real confunde. Se etiqueta como
    # ausencia de cita.
    date_label = trace.date_decision if trace.in_date else "— (sin cita)"
    lines = [
        f"cid `{trace.correlation_id}` · v{trace.version} · {trace.kind}",
        f"reply: {(trace.reply or '(omitida)')[:300]}",
        f"afinidad: {trace.affinity_before} → {trace.affinity_after} "
        f"(aplicado {trace.affinity_applied:+d})",
        f"nivel: {trace.level_before} → {trace.level_after}"
        + (" 🆙" if trace.leveled_up else ""),
        f"gif: {trace.gif} · grounded: {trace.grounded} · "
        f"in_date: {trace.in_date} · skipped: {trace.skipped}",
        f"memoria: {trace.memory_saved} · diario: {trace.diary_saved} "
        f"· decisión cita: {date_label}",
        f"web: {'sí' if trace.web_context else 'no'} · llm: {trace.llm_ms} ms "
        f"· turno: {trace.turn_ms} ms",
    ]
    if trace.web_query:
        lines.append(f"query: {trace.web_query[:200]}")
    if trace.error:
        lines.append(f"error: {trace.error}")
    return "\n".join(lines)


def _event_line(ev):
    reply = (ev.final_reply or "").replace("\n", " ")[:60]
    err = f" · errors={len(ev.errors)}" if ev.errors else ""
    head = (
        f"`{ev.correlation_id}` {ev.kind} · "
        f"{ev.user_name or ev.user_id or '-'} · Δ{ev.affinity_applied:+d} "
        f"· {ev.total_latency_ms}ms{err}"
    )
    return head + (f"\n   {reply}" if reply else "")


async def _send_raw_trace(message, trace):
    """Envía la traza como fichero JSON (con raw_llm si la traza lo tiene)."""
    payload = json.dumps(trace.to_dict(), ensure_ascii=False, indent=2)
    data = payload.encode("utf-8")
    filename = f"trace-{trace.correlation_id}.json"
    file = discord.File(io.BytesIO(data), filename=filename)
    await message.channel.send(
        f"Traza `{trace.correlation_id}` ({len(data)} bytes). "
        "Reprodúcela con `airi-replay " + filename + "`",
        file=file,
    )


async def _send_list(message, title, events):
    if not events:
        await message.reply(
            "No hay eventos registrados todavía.", mention_author=False
        )
        return
    body = "\n".join(_event_line(ev) for ev in events)
    embed = discord.Embed(title=title, description=body[:4000])
    await message.channel.send(embed=embed)


def _find_on_disk(trace_dir, cid):
    for ev in load_events_from_dir(trace_dir):
        if ev.correlation_id == cid:
            return ev
    return None


async def handle(ctx, message):
    if ctx.owner_id and message.author.id != ctx.owner_id:
        await message.reply(
            "Solo el dueño del canal puede usar `!debug`.",
            mention_author=False,
        )
        return
    parts = message.content.strip().split()
    sub = parts[1].lower() if len(parts) >= 2 else ""

    if sub == "clear":
        n = len(ctx.state.traces)
        ctx.state.traces.clear()
        await message.reply(
            f"Ring de eventos vaciado ({n} eventos). El disco no se toca.",
            mention_author=False,
        )
        return

    if sub == "estado":
        info = ctx.storage_info if isinstance(ctx.storage_info, dict) else {}
        if not info:
            await message.reply(
                "No hay diagnóstico de almacenamiento disponible.",
                mention_author=False,
            )
            return
        lines = [
            f"ruta: `{info.get('path', '-')}`",
            f"schema_version: {info.get('schema_version', '-')}",
            f"state_version: {info.get('state_version', '-')}",
            f"recuperado: {'sí' if info.get('recovered') else 'no'}",
            f"migración: {info.get('migration') or 'ninguna'}",
            f"publicaciones pendientes: {info.get('pending_publications', 0)}",
        ]
        quarantine = info.get("quarantine_path")
        if quarantine:
            lines.append(f"cuarentena: `{quarantine}`")
        embed = discord.Embed(
            title="🗄️ Estado persistente",
            description="\n".join(lines)[:4000],
        )
        await message.channel.send(embed=embed)
        return

    if sub == "ultimo":
        n = 1
        if len(parts) >= 3:
            try:
                n = int(parts[2])
            except ValueError:
                await message.reply(DEBUG_USAGE, mention_author=False)
                return
            n = max(1, min(MAX_LIST, n))
        events = ctx.state.traces.last(n)
        await _send_list(message, f"🧾 Últimos {n} evento(s)", events)
        return

    if sub == "errores":
        events = [ev for ev in ctx.state.traces.all() if ev.errors or ev.error]
        events = list(reversed(events[-MAX_ERRORS:]))
        if not events:
            await message.reply(
                "No hay errores registrados. 🎉", mention_author=False
            )
            return
        await _send_list(message, f"⚠️ Eventos con errores ({len(events)})", events)
        return

    if sub == "id":
        cid = parts[2] if len(parts) >= 3 else ""
        if not cid:
            await message.reply(DEBUG_USAGE, mention_author=False)
            return
        ev = ctx.state.traces.by_correlation_id(cid)
        if ev is None and ctx.trace_dir:
            ev = _find_on_disk(ctx.trace_dir, cid)
        if ev is None:
            await message.reply(
                f"No encontré la traza `{cid}`.", mention_author=False
            )
            return
        if not isinstance(ev, TurnTrace):
            ev = TurnTrace.from_dict(dict(ev))
        await _send_raw_trace(message, ev)
        return

    if sub in ("turno", "trace"):
        trace = ctx.last_trace_for(message.channel.id, message.author.id)
        if trace is None:
            await message.reply(
                "No hay ningún turno registrado para ti todavía. "
                f"Habla primero con {character_name()} y vuelve a intentarlo.",
                mention_author=False,
            )
            return
        if sub == "trace":
            if not isinstance(trace, TurnTrace):
                trace = TurnTrace.from_dict(dict(trace))
            await _send_raw_trace(message, trace)
            return
        embed = discord.Embed(
            title="🔍 Último turno",
            description=_summarize(trace)[:4000],
        )
        await message.channel.send(embed=embed)
        return

    await message.reply(DEBUG_USAGE, mention_author=False)
