"""Traducción de turnos de conversación/cita a mensajes de Discord.

Contiene el antiguo `run_user_turn` y los callbacks de los botones de cita.
No habla directamente con llama.cpp/Brave/NekosBest: usa el `ConversationService`
que construye `ctx.build_service`. Toda la traducción a Discord (embeds, GIFs,
botones) vive aquí.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from io import BytesIO

import aiohttp
import discord

from airi.discord_bot import embeds
from airi.discord_bot.views import date as date_views
from airi.domain.affinity import can_date, entry_points
from airi.domain.constants import (
    DATE_COOLDOWN,
    DATE_QUESTION_MIN_SECONDS,
    DATE_QUESTION_TIME_MARGIN,
    DATE_QUESTION_TIMEOUT,
    DATE_SCENE_TEXT_MAX,
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

log = logging.getLogger(__name__)


def sanitize_scene(scene, limit=DATE_SCENE_TEXT_MAX):
    """Normaliza la escena escrita por el jugador (una línea, recortada)."""
    text = " ".join(str(scene or "").split())
    return text[:limit].strip()


async def send_long_message(channel, content, *, reference=None):
    """Envía un texto del modelo troceado en bloques de 2000 caracteres.

    Es la vía de las respuestas genuinas del LLM: van en texto plano (como un
    mensaje normal de Discord), nunca dentro de un embed. El primer bloque se
    enhebra bajo `reference` para que quede como una respuesta.
    """
    content = clean_reply(content) or (
        "Ehhh... no he conseguido preparar una respuesta esta vez."
    )
    first = True
    while content:
        chunk = content[:2000]
        content = content[2000:]
        if first and reference is not None:
            await channel.send(chunk, reference=reference, mention_author=False)
        else:
            await channel.send(chunk)
        first = False


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
    allow_crisis_drop=None,
):
    """Procesa un turno (texto libre o reacción a la pregunta) y lo traduce a Discord."""
    channel_id = channel.id
    author_id = author.id
    reaction = kind == "date_question_result"
    if allow_crisis_drop is None:
        allow_crisis_drop = not reaction

    async def _reply(text):
        # Mensajes de sistema del turno (errores, ausencia de respuesta): embed.
        await channel.send(
            embed=embeds.system_embed(text),
            reference=reply_target,
            mention_author=False,
        )

    async with ctx.lock:
        state = ctx.state
        timeout = aiohttp.ClientTimeout(total=ctx.request_timeout)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                service = ctx.build_service(session, state, channel)
                merged_text = "\n".join(part for _, part in merged)

                async with channel.typing():
                    async with session.get(
                        f"{ctx.llama_url}/health",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as health:
                        health.raise_for_status()

                    cid = uuid.uuid4().hex[:12]
                    result = await service.run_turn(
                        author,
                        merged,
                        TurnContext(
                            channel_id=channel_id,
                            allow_web=allow_web,
                            correlation_id=cid,
                            kind=kind,
                            extra_note=extra_note,
                            suppress_affinity=suppress_affinity,
                        ),
                    )
                    ctx.remember_trace(result.trace)

                if result.skipped:
                    return
                if not result.reply:
                    await _reply(
                        "Ehhh... no conseguí generar una respuesta final esta vez. "
                        "¿Puedes intentarlo de nuevo?"
                    )
                    return

                answer = result.reply
                now = time.time()
                uid = author_id
                date_session = state.dates.get(str(uid))
                in_date = result.in_date and isinstance(date_session, dict)

                # Respuesta del modelo: SIEMPRE texto plano (como un mensaje
                # normal de Discord), nunca dentro de un embed. Así se separan
                # las respuestas originales del modelo de los avisos del sistema.
                await send_long_message(channel, answer, reference=reply_target)
                await send_gif_bytes(ctx, channel, author, result.gif, result.gif_bytes)

                await ctx.settle_relationship(channel, now, session=session, user=author)

                if in_date:
                    decision = result.date_decision
                    last_chance_result = result.last_chance_result
                    question = result.date_question
                    if reaction:
                        # Turno interno: el motor ya aplicó el swing. Solo puede
                        # forzar la crisis (fallo grave); nunca cierra ni re-pregunta.
                        decision = "crisis" if date_session.get("force_crisis") else "continue"
                        last_chance_result = "none"
                        question = None
                    date_event = await ctx.process_date_turn(
                        channel,
                        author,
                        date_session,
                        http_session=session,
                        text=merged_text,
                        delta=result.affinity_delta,
                        points=state.entry_points(uid),
                        date_decision=decision,
                        date_reason=result.date_reason,
                        last_chance_result=last_chance_result,
                        now=now,
                        question=question,
                        allow_crisis_drop=allow_crisis_drop,
                    )
                    # El paso de cita ocurre fuera de `run_turn`; volcamos el
                    # evento a la traza y la reescribimos para que el replay
                    # pueda reproducirlo de forma fiel.
                    if result.trace is not None:
                        result.trace.date_event = date_event
                        result.trace.date_end_keyword = date_session.get("end_keyword")
                        result.trace.date_question_forced = bool(
                            date_session.get("question_forced")
                        )
                        result.trace.date_question_invalid = bool(
                            date_session.get("question_invalid")
                        )
                        await state.traces.update(result.trace)
                    # Embed de estado en CADA turno de cita. La respuesta del
                    # modelo va en texto plano; aquí se muestra la fase, los
                    # turnos y el tiempo restantes tras avanzar el turno.
                    await channel.send(
                        embed=date_views.date_status_embed(
                            date_session.get("scene"),
                            state=date_session.get("state", "active"),
                            turns_left=date_turns_left(date_session),
                            seconds_left=date_seconds_left(date_session, now),
                        )
                    )
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
                    if date_event == "question" and isinstance(
                        date_session.get("question"), dict
                    ):
                        await _send_question(
                            ctx, channel, uid, date_session, now=now
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
            await channel.send(
                embed=embeds.system_embed(DATE_QUESTION_MISSED_TEXT)
            )
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
        on_expire=lambda: ctx.expire_question(uid, notify_channel=channel),
    )
    await channel.send(
        embed=date_views.build_question_embed(question.get("text", "")),
        view=view,
    )


async def start_date_with_scene(ctx, channel, user, scene):
    """Arranca la cita con la escena escrita por el jugador.

    Revalida los requisitos (nadie más en cita, nivel mínimo, cooldown) porque
    entre el `!cita` y la respuesta puede pasar tiempo.
    """
    uid = user.id
    state = ctx.state
    owner_id, owner_session = ctx.busy_date_owner(exclude_id=uid)
    if owner_id is not None:
        await channel.send(embed=embeds.system_embed(ctx.date_busy_text(owner_id, owner_session)))
        return False
    if str(uid) in state.dates:
        await channel.send(
            embed=embeds.system_embed(
                "¡Ya estáis en una cita! *se ríe* concéntrate en el momento~"
            )
        )
        return False
    entry = state.affinity_entry(uid)
    points = entry_points(entry)
    if not can_date(points):
        await channel.send(
            embed=embeds.system_embed(
                "Ehh... *se rasca la mejilla* todavía no te conozco lo suficiente "
                "para una cita. Llega a ser mi **amiga** y te diré que sí, ¿vale?"
            )
        )
        return False
    scene = sanitize_scene(scene)
    if not scene:
        return False
    now = time.time()
    last_date = float(entry.get("last_date", 0.0) or 0.0)
    if now - last_date < DATE_COOLDOWN:
        remaining = int((DATE_COOLDOWN - (now - last_date)) // 3600)
        await channel.send(
            embed=embeds.system_embed(
                f"Airi ya ha salido contigo hace poco... dale un respiro "
                f"(en ~{remaining} h)."
            )
        )
        return False
    async with turn_event(
        state,
        kind="scene_select",
        user=user,
        channel_id=getattr(channel, "id", ""),
        raw_input=scene,
    ):
        state.dates[str(uid)] = new_date_session(scene, points, now)
        entry["last_date"] = now
        state.save_affinity()
        state.save_dates()
        await channel.send(embed=embeds.system_embed(date_intro(scene)))
    return True


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
            embed=embeds.system_embed("Esa pregunta ya no está esperando respuesta~"),
            ephemeral=True,
        )
        return
    now = time.time()
    if date_expired(session, now):
        ctx.expire_stale_dates(now)
        await interaction.followup.send(
            embed=embeds.system_embed("Esa cita ya ha terminado~"), ephemeral=True
        )
        return
    result = ctx.resolve_question(session, option_index)
    if result is None:
        await interaction.followup.send(
            embed=embeds.system_embed("Esa opción ya no está disponible~"),
            ephemeral=True,
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
