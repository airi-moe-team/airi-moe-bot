"""Traducción de turnos de conversación/cita a mensajes de Discord.

Contiene el antiguo `run_user_turn` y los callbacks de los botones de cita.
No habla directamente con llama.cpp/Brave/NekosBest: usa el `ConversationService`
que construye `ctx.build_service`. Toda la traducción a Discord (embeds, GIFs,
botones) vive aquí.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from contextlib import nullcontext
from io import BytesIO

import aiohttp
import discord

from airi.adapters.http_llm import health_check
from airi.discord_bot import embeds
from airi.discord_bot.persistence import async_state_transaction, state_transaction
from airi.discord_bot.views import date as date_views
from airi.domain.affinity import can_date, entry_points
from airi.domain.constants import (
    DATE_COOLDOWN,
    DATE_QUESTION_MIN_SECONDS,
    DATE_QUESTION_TIME_MARGIN,
    DATE_QUESTION_TIMEOUT,
    DATE_SCENES,
)
from airi.domain.dates import (
    date_expired,
    date_seconds_left,
    date_turns_left,
    new_date_session,
)
from airi.domain.gifs import ALLOWED_GIF_TYPES, GIF_EMOTION_TITLES
from airi.domain.text_filters import clean_reply
from airi.domain.texts import (
    DATE_QUESTION_MISSED_TEXT,
    date_intro,
    date_question_result_note,
)
from airi.observability.instrumentation import turn_event
from airi.services.conversation import TurnContext
from airi.services.persistence import PersistenceError
from airi.services.turn_coordinator import StaleTurnError, TurnCoordinator

log = logging.getLogger(__name__)


async def send_long_message(channel, content, *, reference=None):
    """Envía un texto largo; el primer bloque responde al mensaje origen."""
    content = clean_reply(content) or (
        "Ehhh... no he conseguido preparar una respuesta esta vez."
    )
    first_chunk = True
    while content:
        chunk = content[:2000]
        content = content[2000:]
        if first_chunk and reference is not None:
            await channel.send(chunk, reference=reference, mention_author=False)
        else:
            await channel.send(chunk)
        first_chunk = False


async def send_gif_bytes(ctx, channel, user, gif_type, data):
    """Envía el GIF obtenido (bytes) como embed con el pie de afinidad."""
    if not data or gif_type == "none" or gif_type not in ALLOWED_GIF_TYPES:
        return
    log.info("El modelo ha seleccionado el GIF: %s", gif_type)
    try:
        filename = f"airi_{gif_type}.gif"
        embed = discord.Embed(
            title=GIF_EMOTION_TITLES.get(gif_type, "Airi"),
            color=embeds.GIF_EMBED_COLOR,
        )
        if user is not None:
            embed.set_footer(
                text=ctx.affinity_footer(user),
                icon_url=user.display_avatar.url,
            )
        embed.set_image(url=f"attachment://{filename}")
        file = discord.File(BytesIO(data), filename=filename)
        await channel.send(embed=embed, file=file)
        log.info("GIF enviado correctamente: %s", gif_type)
    except discord.HTTPException:
        log.exception("Discord no pudo enviar el GIF")


async def run_user_turn(
    ctx,
    channel,
    author,
    merged,
    *,
    allow_web=True,
    reply_target=None,
    kind="message",
    extra_note=None,
    suppress_affinity=False,
):
    """Procesa un turno (texto libre o botón de cita) y lo traduce a Discord."""
    channel_id = channel.id
    author_id = author.id
    is_shutting_down = getattr(ctx, "is_shutting_down", None)
    if callable(is_shutting_down) and is_shutting_down():
        return

    async def _reply(text):
        await channel.send(text, reference=reply_target, mention_author=False)

    state = ctx.state
    timeout = aiohttp.ClientTimeout(total=ctx.request_timeout)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            service = ctx.build_service(session, state, channel)
            merged_text = "\n".join(part for _, part in merged)
            result = None
            published = False

            async with channel.typing():
                await health_check(
                    session,
                    provider=getattr(ctx, "llm_provider", "llama"),
                    base_url=ctx.llm_base_url,
                    enabled=getattr(ctx, "llm_health_check", True),
                )

                cid = uuid.uuid4().hex[:12]
                turn_ctx = TurnContext(
                    channel_id=channel_id,
                    allow_web=allow_web,
                    correlation_id=cid,
                    kind=kind,
                    extra_note=extra_note,
                    suppress_affinity=suppress_affinity,
                )
                journal = getattr(ctx, "turn_journal", None)
                persistence = getattr(ctx, "persistence", None)
                message_id = getattr(reply_target, "id", None)
                if journal is not None and persistence is not None and message_id is not None:
                    async def publisher(committed):
                        await _publish_result(
                            ctx,
                            channel,
                            author,
                            committed.result,
                            reply_target=reply_target,
                        )

                    coordinator = TurnCoordinator(
                        service=service,
                        journal=journal,
                        persistence=persistence,
                        commit_lock=getattr(ctx, "commit_lock", None),
                        clock=time.time,
                    )
                    result = await coordinator.execute(
                        channel_id=channel_id,
                        user=author,
                        messages=merged,
                        message_ids=[message_id],
                        context=turn_ctx,
                        publisher=publisher,
                    )
                    published = True
                else:
                    result = await service.run_turn(author, merged, turn_ctx)

                if result is not None:
                    ctx.remember_trace(result.trace)

            if result is None:
                return
            if result.skipped:
                # Nunca dejar el mensaje sin respuesta: si el filtro descartó
                # una repetición, se pide contexto en vez de quedarse callada.
                await _reply(
                    "Mmm... siento que ya te había dicho algo muy parecido. "
                    "¿Me cuentas un poco más para no repetirme?"
                )
                return
            if not result.reply:
                await _reply(
                    "Ehhh... no conseguí generar una respuesta final esta vez. "
                    "¿Puedes intentarlo de nuevo?"
                )
                return

            if not published:
                await _publish_result(
                    ctx, channel, author, result, reply_target=reply_target
                )

            # El motivo del cierre anterior es de un solo uso: solo se marca
            # entregado cuando la respuesta ya se publicó correctamente.
            acknowledge = getattr(ctx, "acknowledge_reconnect_context", None)
            if callable(acknowledge):
                await acknowledge()

            now = time.time()
            uid = author_id
            date_session = state.dates.get(str(uid))
            in_date = result.in_date and isinstance(date_session, dict)

            if in_date:
                lock = getattr(ctx, "commit_lock", None)
                deferred = getattr(ctx, "persistence", None) is not None
                async with (lock or nullcontext()):
                    with state_transaction(ctx):
                        if deferred:
                            date_event, date_notices = await ctx.process_date_turn(
                                channel,
                                author,
                                date_session,
                                text=merged_text,
                                delta=result.affinity_delta,
                                points=state.entry_points(uid),
                                date_decision=result.date_decision,
                                date_reason=result.date_reason,
                                last_chance_result=result.last_chance_result,
                                now=now,
                                question=result.date_question,
                                defer=True,
                            )
                        else:
                            date_event = await ctx.process_date_turn(
                                channel,
                                author,
                                date_session,
                                text=merged_text,
                                delta=result.affinity_delta,
                                points=state.entry_points(uid),
                                date_decision=result.date_decision,
                                date_reason=result.date_reason,
                                last_chance_result=result.last_chance_result,
                                now=now,
                                question=result.date_question,
                            )
                            date_notices = []
                for notice in date_notices:
                    await channel.send(
                        embed=embeds.system_embed(notice, title="🌙 Cita")
                    )
                # El paso de cita ocurre fuera de `run_turn`; volcamos el
                # evento a la traza y la reescribimos para que el replay
                # pueda reproducirlo de forma fiel.
                if result.trace is not None:
                    result.trace.date_event = date_event
                    await state.traces.update(result.trace)
                if (
                    date_event
                    in (
                        "ending",
                        "recovered",
                        "partial_recovery",
                        "failed_last_chance",
                    )
                    and not result.diary_saved
                    and result.diary_action.lower() != "none"
                ):
                    ctx.add_diary_reflection(uid, result.diary_action, now=now)
                # La cita NO lleva botones en cada turno: solo se publica la
                # pregunta decisiva (una sola vez) con sus alternativas.
                if date_event == "question" and isinstance(
                    date_session.get("question"), dict
                ):
                    await _send_question(
                        ctx, channel, uid, date_session, now=now
                    )

            # Reflexión automática: se comprueba después del commit y se
            # ejecuta en segundo plano para no retrasar la respuesta.
            maybe_reflect = getattr(ctx, "maybe_reflect", None)
            if (
                callable(maybe_reflect)
                and not result.disconnect_reason
                and not (callable(getattr(ctx, "is_shutting_down", None)) and ctx.is_shutting_down())
            ):
                interactions = int(
                    (state.users.get(str(uid)) or {}).get("interactions", 0) or 0
                )
                if state.should_reflect_self(interactions=interactions, now=now):
                    asyncio.create_task(maybe_reflect(uid, now))

            # La marcha se solicita al final: la despedida y los efectos
            # confirmados del turno/cita ya se publicaron y persistieron.
            if result.disconnect_reason:
                await ctx.request_shutdown(
                    result.disconnect_reason, user_id=author_id
                )

    except StaleTurnError:
        log.warning("Turno descartado porque el estado cambió durante la generación")
        await _reply(
            "Uy... la conversación cambió mientras pensaba. "
            "¿Me lo repites, por favor?"
        )
    except PersistenceError:
        log.exception("No se pudo confirmar el turno")
        await _reply(
            "No he podido guardar lo que ha pasado, así que no voy a fingir "
            "que ocurrió. ¿Lo intentamos otra vez?"
        )
    except asyncio.TimeoutError:
        log.warning("Tiempo de espera agotado")
        await _reply(
            "¡Ups! El modelo está tardando demasiado. "
            "Inténtalo de nuevo en un momentito."
        )
    except aiohttp.ClientResponseError as exc:
        log.exception("Un servicio HTTP devolvió un error: %s", exc.status)
        await _reply(
            "No pude completar la petición a un servicio. "
            "Revisa los registros del bot."
        )
    except aiohttp.ClientError:
        log.exception("Error comunicándose con un servicio HTTP")
        await _reply(
            "No puedo conectar con el modelo local o con un servicio necesario. "
            "Comprueba que llama-server siga funcionando."
        )
    except (KeyError, IndexError, ValueError):
        log.exception("Respuesta inesperada del modelo")
        await _reply("El modelo devolvió una respuesta inesperada.")
    except discord.HTTPException:
        log.exception("Discord no pudo procesar el mensaje")
    except Exception:
        log.exception("Error procesando el mensaje")
        await _reply("¡Ay! Ha ocurrido un error inesperado al responder.")


async def _publish_result(ctx, channel, author, result, *, reply_target=None):
    """Publica una respuesta ya confirmada y sus avisos post-commit."""
    now = time.time()
    uid = author.id
    date_session = ctx.state.dates.get(str(uid))
    if result.in_date and isinstance(date_session, dict):
        embed = date_views.build_date_embed(
            result.reply,
            scene=date_session.get("scene"),
            state=date_session.get("state", "active"),
            turns_left=date_turns_left(date_session),
            seconds_left=date_seconds_left(date_session, now),
        )
        try:
            if reply_target is not None:
                await channel.send(
                    embed=embed,
                    reference=reply_target,
                    mention_author=False,
                )
            else:
                await channel.send(embed=embed)
        except discord.HTTPException:
            await send_long_message(
                channel, result.reply, reference=reply_target
            )
    else:
        await send_long_message(channel, result.reply, reference=reply_target)
    await send_gif_bytes(ctx, channel, author, result.gif, result.gif_bytes)
    for notice in result.notices:
        try:
            await channel.send(embed=embeds.notice_embed(notice))
        except discord.HTTPException:
            log.warning("No se pudo enviar el aviso post-turno")


async def _send_question(ctx, channel, uid, date_session, *, now):
    """Publica la pregunta decisiva con sus botones (una sola vez por cita).

    Nunca la lanza si a la cita le queda menos de `DATE_QUESTION_MIN_SECONDS`:
    en ese caso se cancela (no dejar `question_pending` colgado) y se avisa. Si
    la pregunta es la de reserva (forzada), se alarga la cita lo justo para que
    sea respondible: la pregunta decisiva siempre debe poder contestarse.
    """
    question = date_session.get("question") or {}
    options = question.get("options") or []
    remaining = int(date_seconds_left(date_session, now))

    if remaining < DATE_QUESTION_MIN_SECONDS:
        if not date_session.get("question_forced"):
            ctx.expire_question(uid)
            await channel.send(DATE_QUESTION_MISSED_TEXT)
            return
        missing = DATE_QUESTION_MIN_SECONDS - remaining + DATE_QUESTION_TIME_MARGIN
        date_session["started_at"] = float(date_session.get("started_at", now)) + missing
        ctx.state.save_dates()
        remaining = int(date_seconds_left(date_session, now))

    view = date_views.DateQuestionView(
        uid,
        options,
        ctx.handle_question_answer,
        timeout=max(DATE_QUESTION_MIN_SECONDS, min(remaining, DATE_QUESTION_TIMEOUT)),
        on_expire=lambda: ctx.expire_question(uid),
    )
    await channel.send(
        embed=date_views.build_question_embed(question.get("text", "")),
        view=view,
    )


async def handle_question_answer(ctx, interaction, option_index):
    """Resuelve la pregunta decisiva cuando el jugador pulsa un botón.

    El motor tira el dado y aplica el swing (±25); después Airi reacciona en un
    turno extra (sin volver a mover la afinidad ni repetir la pregunta).
    """
    user = interaction.user
    uid = str(user.id)
    state = ctx.state
    session = state.dates.get(uid)
    if (
        not isinstance(session, dict)
        or session.get("state") != "active"
        or not session.get("question_pending")
    ):
        await interaction.followup.send(
            "Esa pregunta ya no está esperando respuesta~", ephemeral=True
        )
        return
    now = time.time()
    if date_expired(session, now):
        ctx.expire_stale_dates(now)
        await interaction.followup.send("Esa cita ya ha terminado~", ephemeral=True)
        return
    result = ctx.resolve_question(session, option_index)
    if result is None:
        await interaction.followup.send(
            "Esa opción ya no está disponible~", ephemeral=True
        )
        return
    ctx.apply_question_result(session, result, user_id=user.id, now=now)
    note = date_question_result_note(result["win"], result["delta"])
    action = result.get("action") or result.get("label") or "responde"
    await run_user_turn(
        ctx,
        interaction.channel,
        user,
        [(user, action)],
        allow_web=False,
        kind="date_question_result",
        extra_note=note,
        suppress_affinity=True,
    )


async def handle_scene_choice(ctx, interaction, scene):
    """Arranca la cita cuando el jugador elige (o sortea) una escena."""
    user = interaction.user
    uid = user.id
    state = ctx.state
    owner_id, owner_session = ctx.busy_date_owner(exclude_id=uid)
    if owner_id is not None:
        await interaction.followup.send(
            ctx.date_busy_text(owner_id, owner_session), ephemeral=True
        )
        return
    if str(uid) in state.dates:
        await interaction.followup.send(
            "¡Ya estáis en una cita! *se ríe* concéntrate en el momento~",
            ephemeral=True,
        )
        return
    entry = state.affinity_entry(uid)
    points = entry_points(entry)
    if not can_date(points):
        await interaction.followup.send(
            "Ehh... *se rasca la mejilla* todavía no te conozco lo suficiente "
            "para una cita. Llega a ser mi **amiga** y te diré que sí, ¿vale?",
            ephemeral=True,
        )
        return
    now = time.time()
    last_date = float(entry.get("last_date", 0.0) or 0.0)
    if now - last_date < DATE_COOLDOWN:
        remaining = int((DATE_COOLDOWN - (now - last_date)) // 3600)
        await interaction.followup.send(
            f"Airi ya ha salido contigo hace poco... dale un respiro "
            f"(en ~{remaining} h).",
            ephemeral=True,
        )
        return
    if not scene:
        scene = random.choice(DATE_SCENES)
    async with turn_event(
        state,
        kind="scene_select",
        user=user,
        channel_id=getattr(interaction.channel, "id", ""),
        raw_input=scene,
    ):
        async with async_state_transaction(ctx):
            state.dates[str(uid)] = new_date_session(scene, points, now)
            entry["last_date"] = now
            state.save_affinity()
            state.save_dates()
        await interaction.channel.send(date_intro(scene))


async def handle_date_action(ctx, interaction, action_text):
    """Ejecuta un turno de cita a partir de un botón de acción de Airi.

    Las citas ya no ofrecen botones por turno (la conversación fluye sola);
    este manejador se conserva para compatibilidad con citas en curso que
    tuvieran botones de la versión anterior.
    """
    user = interaction.user
    uid = str(user.id)
    state = ctx.state
    session = state.dates.get(uid)
    if not isinstance(session, dict) or session.get("state") == "closed":
        await interaction.followup.send("Esa cita ya ha terminado~", ephemeral=True)
        return
    now = time.time()
    if date_expired(session, now):
        ctx.expire_stale_dates(now)
        await interaction.followup.send("Esa cita ya ha terminado~", ephemeral=True)
        return
    if not action_text:
        return
    await run_user_turn(
        ctx,
        interaction.channel,
        user,
        [(user, action_text)],
        allow_web=False,
        kind="date_action",
    )
