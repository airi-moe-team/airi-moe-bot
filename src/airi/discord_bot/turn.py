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
    MOOD_ENABLED,
)
from airi.domain.dates import (
    date_expired,
    date_seconds_left,
    date_turns_left,
    new_date_session,
)
from airi.domain.gifs import ALLOWED_GIF_TYPES, GIF_EMOTION_TITLES
from airi.domain.mood import (
    mood_category_color,
    normalize_history,
    normalize_mood,
    render_mood_meter,
)
from airi.domain.self_model import normalize_self, render_trait_bars
from airi.domain.notices import discovery_notice, self_changed_notice
from airi.domain.text_filters import clean_reply
from airi.domain.texts import (
    DATE_QUESTION_MISSED_TEXT,
    date_intro,
    date_question_result_note,
)
from airi.observability.instrumentation import turn_event
from airi.observability.interaction_tracker import current_tracker
from airi.services.conversation import TurnContext
from airi.services.persistence import PersistenceError
from airi.services.turn_coordinator import StaleTurnError, TurnCoordinator

log = logging.getLogger(__name__)


def _finalize_spectator_turn(
    ctx,
    channel,
    author,
    kind,
    spectator_reason,
    spectator_snapshot,
    spectator_guaranteed,
    *,
    handoff=False,
    trigger_ids=(),
):
    """Cierra el ciclo del modo espectador tras publicar con éxito.

    - Se consumen del buffer el snapshot y los mensajes del turno (trigger);
      el tema no queda latente tras la intervención.
    - El cooldown se arma para señales espontáneas Y handoff; la mención
      directa no lo penaliza.
    - La intervención de Airi puede haber dejado una pregunta: habilita UN
      handoff para ese interlocutor dentro de la ventana; tras el handoff la
      cadena termina y solo vuelven los disparadores normales.
    """
    if kind not in ("spectator", "proactive"):
        return
    buffer = getattr(ctx, "passive_buffer", None)
    gate = getattr(ctx, "spectator_gate", None)
    if buffer is not None:
        consumed = []
        for entry in spectator_snapshot:
            entry_id = ""
            if isinstance(entry, dict):
                entry_id = str(entry.get("message_id", "") or "")
            else:
                entry_id = str(getattr(entry, "message_id", "") or "")
            if entry_id:
                consumed.append(entry_id)
        consumed.extend(str(item) for item in trigger_ids if str(item))
        if consumed:
            buffer.mark_consumed(channel.id, consumed)
    if (
        gate is not None
        and not spectator_guaranteed
        and spectator_reason in ("topic", "affinity", "handoff")
    ):
        gate.arm(channel.id, author.id)
    if gate is None:
        return
    if handoff:
        gate.clear_handoff(channel.id, author.id)
    else:
        gate.arm_handoff(channel.id, author.id)


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


def affinity_footer_for_change(ctx, user, affinity_delta):
    """Pie de afinidad para respuestas a un usuario.

    Muestra siempre el total acumulado cuando hay usuario (la relación no
    desaparece entre turnos). Si el turno movió puntos, se añade el delta
    explícito entre paréntesis, p. ej. "· (+1)". Sin usuario (turnos
    proactivos/pending) no hay pie.
    """
    if user is None:
        return ""
    base = ctx.affinity_footer(user)
    if not base:
        return ""
    if affinity_delta:
        return f"{base} ({int(affinity_delta):+d})"
    return base


def traits_summary(ctx):
    """Resumen compacto de los rasgos actuales de Airi (o \"\" si no hay)."""
    state = getattr(ctx, "state", None)
    if state is None:
        return ""
    try:
        model = state.self_model()
    except Exception:
        return ""
    try:
        normalize_self(model)
    except Exception:
        pass
    traits = (model or {}).get("traits") or {}
    return render_trait_bars(traits)


def mood_summary(ctx):
    """Resumen visible del ánimo: categorías con barra (o "" si no hay)."""
    if not MOOD_ENABLED:
        return ""
    state = getattr(ctx, "state", None)
    world = getattr(state, "world", None) or {}
    mood = normalize_mood(world.get("mood"))
    if mood is None:
        return ""
    history = normalize_history(world.get("mood_history"))
    previous = history[-2] if len(history) >= 2 else None
    return render_mood_meter(mood, previous=previous)


def mood_embed_color(ctx):
    """Color del embed según la categoría principal (None si no hay ánimo)."""
    if not MOOD_ENABLED:
        return None
    state = getattr(ctx, "state", None)
    world = getattr(state, "world", None) or {}
    mood = normalize_mood(world.get("mood"))
    if mood is None:
        return None
    return discord.Color(mood_category_color(mood))


async def send_gif_bytes(ctx, channel, user, gif_type, data, *, affinity_delta=0):
    """Envía el embed emocional con el GIF y, si hubo cambio, la afinidad.

    Si el proveedor no devolvió bytes, el embed se envía igualmente sin imagen:
    la afinidad del turno nunca debe desaparecer por un fallo de NekosBest.
    """
    if gif_type == "none" or gif_type not in ALLOWED_GIF_TYPES:
        return
    log.info("El modelo ha seleccionado el GIF: %s", gif_type)
    _gif_tracker = current_tracker()
    if _gif_tracker is not None:
        _gif_tracker.module_result("gif", "activated")
    try:
        embed = discord.Embed(
            title=GIF_EMOTION_TITLES.get(gif_type, "Airi"),
            color=mood_embed_color(ctx) or embeds.GIF_EMBED_COLOR,
        )
        # Rasgos de Airi encima de la imagen (Discord pinta los campos antes
        # que la imagen grande).
        if user is not None:
            traits = traits_summary(ctx)
            if traits:
                embed.add_field(
                    name="Rasgos de Airi", value=traits, inline=False
                )
        mood_text = mood_summary(ctx)
        if mood_text:
            embed.add_field(
                name="Ánimo de Airi", value=mood_text, inline=False
            )
        footer = affinity_footer_for_change(ctx, user, affinity_delta)
        if footer:
            avatar = getattr(user, "display_avatar", None)
            embed.set_footer(
                text=footer,
                icon_url=avatar.url if avatar is not None else None,
            )
        if data:
            filename = f"airi_{gif_type}.gif"
            embed.set_image(url=f"attachment://{filename}")
            file = discord.File(BytesIO(data), filename=filename)
            await channel.send(embed=embed, file=file)
            log.info("GIF enviado correctamente: %s", gif_type)
        else:
            await channel.send(embed=embed)
            log.warning(
                "El proveedor no devolvió el GIF %s; se envió solo la afinidad",
                gif_type,
            )
    except discord.HTTPException:
        log.exception("Discord no pudo enviar el GIF")


def _turn_consumed_ids(
    consumed_message_ids=(), spectator_trigger_ids=(), spectator_snapshot=()
):
    """IDs de mensajes que el turno incorporó y que quedan atendidos."""
    ids = {str(message_id) for message_id in consumed_message_ids if message_id}
    ids.update(str(message_id) for message_id in spectator_trigger_ids if message_id)
    ids.update(
        str(entry.get("message_id"))
        for entry in spectator_snapshot
        if isinstance(entry, dict) and entry.get("message_id")
    )
    return ids


def _mark_turn_answered(ctx, channel, reply_target, consumed_ids):
    """Marca como respondidos todos los mensajes cubiertos por el turno.

    No basta con el `reply_target`: un turno de espectador también responde
    sobre los mensajes del snapshot pasivo, y el debounce puede agrupar varios.
    Se marca solo cuando el publisher confirma la publicación (invariante I3).
    """
    tracker = getattr(ctx, "pending_message_tracker", None)
    if tracker is None:
        return
    ids = {str(message_id) for message_id in consumed_ids if message_id}
    message_id = getattr(reply_target, "id", None)
    if message_id is not None:
        ids.add(str(message_id))
    if ids:
        tracker.mark_answered_many(channel.id, ids)


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
    spectator_reason="",
    spectator_snapshot=(),
    spectator_guaranteed=False,
    spectator_handoff=False,
    spectator_trigger_ids=(),
    consumed_message_ids=(),
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
    registry = getattr(ctx, "spectator_session", None)
    if registry is not None:
        registry.mark_turn_started(channel.id)
    if registry is not None and kind in ("spectator", "proactive"):
        try:
            gen = registry.session(channel.id).generation
            registry.begin_waking(channel.id, gen)
        except Exception:
            log.exception("No se pudo abrir el despertar")

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
                    conversation_mode=(
                        kind if kind in ("spectator", "active", "proactive") else "normal"
                    ),
                    conversation_reason=spectator_reason,
                    extra_note=extra_note,
                    suppress_affinity=suppress_affinity,
                    spectator_reason=spectator_reason,
                    spectator_snapshot=tuple(spectator_snapshot),
                )
                journal = getattr(ctx, "turn_journal", None)
                persistence = getattr(ctx, "persistence", None)
                message_id = getattr(reply_target, "id", None)
                consumed_ids = _turn_consumed_ids(
                    consumed_message_ids,
                    spectator_trigger_ids,
                    spectator_snapshot,
                )
                _turn_tracker = current_tracker()
                if (
                    _turn_tracker is not None
                    and journal is not None
                    and persistence is not None
                    and message_id is not None
                ):
                    _turn_tracker.module_result("persistence", "activated")
                if journal is not None and persistence is not None and message_id is not None:
                    async def publisher(committed):
                        await _publish_result(
                            ctx,
                            channel,
                            author,
                            committed.result,
                            reply_target=reply_target,
                            suppress_affinity=turn_ctx.suppress_affinity,
                        )
                        # Registrar como respondidos todos los mensajes que el
                        # turno cubrió (invariante I2).
                        _mark_turn_answered(ctx, channel, reply_target, consumed_ids)

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
                    _trace_tracker = current_tracker()
                    if _trace_tracker is not None:
                        _trace_tracker.module_result("traces", "activated")

            if result is None:
                return
            session_mode = kind in ("spectator", "active", "proactive")
            silent = session_mode and result.reply == ""

            if result.skipped or (not result.reply and not silent):
                # Nunca dejar el mensaje sin respuesta. Se avisa del fallo real
                # de generación, sin atribuirlo a una repetición inexistente.
                finish = getattr(
                    getattr(result, "trace", None), "llm_finish_reason", None
                )
                if finish == "length":
                    text = (
                        "Tu pregunta o comentario dejó a Airi pensando tanto que "
                        "se olvidó de responder. _Se quedó mirando al vacío como "
                        "si estuviera resolviendo el sentido de la vida._ "
                        "Inténtalo de nuevo, antes de que le eche humo la cabeza."
                    )
                    title = "🧠 Airi pensó demasiado..."
                else:
                    text = (
                        "No he podido generar una respuesta válida esta vez. "
                        "¿Lo intentamos de nuevo?"
                    )
                    title = "⚠️ Generación fallida"
                await channel.send(
                    embed=embeds.system_embed(text, title=title)
                )
                if registry is not None and kind in ("spectator", "proactive"):
                    try:
                        registry.finish_waking(
                            channel.id, published=False, stay_active=False
                        )
                    except Exception:
                        pass
                return

            if not published and not silent:
                await _publish_result(
                    ctx, channel, author, result, reply_target=reply_target,
                    suppress_affinity=suppress_affinity,
                )
            _pub_tracker = current_tracker()
            if _pub_tracker is not None:
                _pub_tracker.module_result("publication", "activated")

            if kind in ("spectator", "proactive"):
                if silent:
                    # Consumir captura + armar cooldown + abortar sesión.
                    _finalize_spectator_turn(
                        ctx, channel, author, kind, spectator_reason,
                        spectator_snapshot, spectator_guaranteed,
                        handoff=spectator_handoff, trigger_ids=spectator_trigger_ids,
                    )
                    gate = getattr(ctx, "spectator_gate", None)
                    if gate is not None:
                        gate.arm(channel.id, author.id)
                    if registry is not None:
                        try:
                            registry.finish_waking(
                                channel.id, published=False, stay_active=False
                            )
                        except Exception:
                            pass
                else:
                    _finalize_spectator_turn(
                        ctx, channel, author, kind, spectator_reason,
                        spectator_snapshot, spectator_guaranteed,
                        handoff=spectator_handoff, trigger_ids=spectator_trigger_ids,
                    )
                    if registry is not None:
                        try:
                            registry.finish_waking(
                                channel.id, published=True,
                                stay_active=getattr(result, "stay_active", True),
                            )
                        except Exception:
                            pass
            elif kind == "active" and registry is not None:
                try:
                    registry.finish_active_turn(
                        channel.id,
                        stay_active=getattr(result, "stay_active", True),
                        published=bool(result.reply and str(result.reply).strip()),
                        silent=silent,
                    )
                except Exception:
                    pass

            # Armar temporizador de inactividad activa si el canal quedó ACTIVE
            # (cubre turnos proactivo/espectador que transicionan a ACTIVE y el
            # arranque con mensaje pendiente; evita quedarse ACTIVE indefinido).
            try:
                _reg = getattr(ctx, "spectator_session", None)
                _timers = getattr(ctx, "timers", None)
                _dispatcher = getattr(ctx, "dispatcher", None)
                if _reg is not None and _timers is not None and _dispatcher is not None:
                    if _reg.state(channel.id).name == "ACTIVE":
                        key = (str(channel.id), "active")
                        old = _timers.pop(key, None)
                        if old is not None:
                            old.cancel()
                        timeout = getattr(_reg, "active_idle_seconds", 120.0)
                        gen = _reg.session(channel.id).generation
                        async def _active_timer():
                            try:
                                await asyncio.sleep(float(timeout))
                            except asyncio.CancelledError:
                                return
                            async def _job():
                                r = _reg
                                if r.retire_if_idle(channel.id, gen, time.time(), timeout):
                                    log.info(
                                        "Retirada por inactividad en canal %s",
                                        channel.id,
                                    )
                            try:
                                await _dispatcher.submit(channel.id, _job)
                            except Exception:
                                log.exception(
                                    "No se pudo procesar el retiro por inactividad"
                                )
                        _timers[key] = asyncio.create_task(_active_timer())
            except Exception:
                log.exception("No se pudo armar el temporizador de inactividad activa")

            # El motivo del cierre anterior es de un solo uso: solo se marca
            # entregado cuando la respuesta ya se publicó correctamente.
            acknowledge = getattr(ctx, "acknowledge_reconnect_context", None)
            if callable(acknowledge):
                await acknowledge()

            if registry is not None:
                registry.mark_turn_finished(channel.id)

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
                    asyncio.create_task(
                        _reflect_and_publish(channel, uid, now, maybe_reflect)
                    )

            # La marcha se solicita al final: la despedida y los efectos
            # confirmados del turno/cita ya se publicaron y persistieron.
            if result.disconnect_reason:
                correlation_id = (
                    getattr(result.trace, "correlation_id", "")
                    if result.trace is not None
                    else ""
                )
                requested_at = time.time()
                await ctx.request_shutdown(
                    result.disconnect_reason,
                    user_id=author_id,
                    correlation_id=correlation_id,
                )
                if result.trace is not None:
                    result.trace.shutdown_request = {
                        "origin": "model",
                        "reason": result.disconnect_reason,
                        "user_id": str(author_id),
                        "correlation_id": correlation_id,
                        "requested_at": requested_at,
                    }
                    traces = getattr(state, "traces", None)
                    if traces is not None:
                        await traces.update(result.trace)

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


async def _publish_result(ctx, channel, author, result, *, reply_target=None, suppress_affinity=False):
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
    await send_gif_bytes(
        ctx, channel,
        None if suppress_affinity else author,
        result.gif, result.gif_bytes,
        affinity_delta=getattr(result, "affinity_applied", 0),
    )
    for notice in result.notices:
        try:
            await channel.send(embed=embeds.notice_embed(notice))
        except discord.HTTPException:
            log.warning("No se pudo enviar el aviso post-turno")


async def _reflect_and_publish(channel, uid, now, reflect):
    """Ejecuta la reflexión en segundo plano y publica sus avisos."""
    try:
        outcome = await reflect(uid, now)
        if outcome is None:
            return
        notices = []
        if getattr(outcome, "discovery", None):
            notices.append(discovery_notice(user_id=str(uid)))
        if getattr(outcome, "self_entry", None):
            notices.append(self_changed_notice(user_id=str(uid)))
        for notice in notices:
            await channel.send(embed=embeds.notice_embed(notice))
    except Exception:
        log.exception("No se pudo publicar la reflexión automática")


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
