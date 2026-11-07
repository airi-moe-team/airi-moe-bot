"""Cliente de Discord: solo enruta eventos hacia comandos y turnos.

`create_client` recibe un `build_ctx(channel) -> BotContext`, un
`CommandRegistry` y el id del canal autorizado. `on_message` se limita a:
autorizar → expirar citas → despachar comando → comprobar cita activa →
debounce → delegar el turno a `airi.discord_bot.turn`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
import time
from contextlib import nullcontext
from types import SimpleNamespace

import discord

from airi.discord_bot import embeds, turn
from airi.discord_bot.spectator_timers import arm_active_timer
from airi.domain import spectator
from airi.domain.constants import AIRI_SPECTATOR_PENDING_MAX_AGE_SECONDS, DATE_DELTA_MAX
from airi.domain.spectator import load_policy, load_stable_profile
from airi.domain.time_perception import resolve_zone
from airi.observability.interaction_tracker import (
    current_tracker,
    tracked_interaction,
)
from airi.persona import character_name, current_persona
from airi.services import spectator_policy as spectator_policy_module
from airi.services.channel_queue import ChannelDispatcher
from airi.services.conversation_task import ConversationTaskRegistry
from airi.services.passive_buffer import PassiveBuffer, apply_stable_profile
from airi.services.pending_message import PendingMessageTracker
from airi.services.spectator_policy import ActivitiesCooldown
from airi.services.spectator_session import (
    ConversationState,
    SpectatorSessionRegistry,
)

log = logging.getLogger(__name__)

PENDING_MAX_AGE_SECONDS = 86400


def _epoch(value):
    """Convierte un instante (datetime o epoch) a epoch en segundos."""
    timestamp = getattr(value, "timestamp", None)
    if timestamp is not None:
        try:
            return float(timestamp())
        except Exception:
            pass
    try:
        return float(value)
    except Exception:
        return 0.0


def pending_user_message(
    history,
    bot_id,
    *,
    now=None,
    max_age=PENDING_MAX_AGE_SECONDS,
    command_prefix="!",
):
    """Último mensaje del canal si Airi todavía no lo ha contestado."""
    if not history:
        return None
    last = history[0]
    author = getattr(last, "author", None)
    if author is None or getattr(author, "bot", False):
        return None
    if getattr(author, "id", None) == bot_id:
        return None
    content = (getattr(last, "content", "") or "").strip()
    command_like = bool(command_prefix and content.startswith(command_prefix))
    attachments = getattr(last, "attachments", None) or []
    has_media = bool(attachments)
    if command_like:
        return None
    if not content and not has_media:
        return None
    created_at = getattr(last, "created_at", None)
    if max_age is not None and created_at is not None:
        current = _epoch(now) if now is not None else time.time()
        created = _epoch(created_at)
        if now is None and created > current + 86400:
            age = 0
        else:
            age = current - created
        if age >= float(max_age):
            return None
    return last


class _Debouncer:
    """Une mensajes rápidos del MISMO (canal, autor) con sus ids."""

    def __init__(self):
        self.pending = {}
        self.seq = {}
        self.ids = {}

    def next_seq(self, key):
        value = self.seq.get(key, 0) + 1
        self.seq[key] = value
        return value

    def current_seq(self, key):
        return self.seq.get(key)

    def add(self, key, item, *, message_id=None):
        self.pending.setdefault(key, []).append(item)
        if message_id is not None and str(message_id):
            self.ids.setdefault(key, []).append(str(message_id))

    def pop(self, key):
        self.seq.pop(key, None)
        ids = tuple(self.ids.pop(key, []))
        return self.pending.pop(key, []), ids

    def reset(self, channel_id, author_id):
        key = (channel_id, author_id)
        self.pending.pop(key, None)
        self.seq.pop(key, None)
        self.ids.pop(key, None)


async def acknowledge_reconnect_context(ctx):
    """Marca como entregado el motivo del último cierre.

    Se llama solo después de confirmar y publicar el primer turno, para no
    perder el contexto si la generación falla.
    """
    state = getattr(ctx, "state", None)
    world = getattr(state, "world", None)
    entry = world.get("last_shutdown") if isinstance(world, dict) else None
    if not isinstance(entry, dict) or entry.get("context_delivered"):
        return

    persistence = getattr(ctx, "persistence", None)
    if persistence is None:
        entry["context_delivered"] = True
        return

    async with (getattr(ctx, "commit_lock", None) or nullcontext()):
        try:
            with persistence.transaction():
                entry["context_delivered"] = True
                state.save_world()
        except Exception:
            log.exception(
                "No se pudo marcar el contexto de reconexión como entregado"
            )


async def _resolve_startup_channel(discord_client, channel_id):
    """Resuelve el canal del arranque sin romper la conexión si falla."""
    getter = getattr(discord_client, "get_channel", None)
    channel = getter(channel_id) if callable(getter) else None
    if channel is not None:
        return channel
    fetcher = getattr(discord_client, "fetch_channel", None)
    if not callable(fetcher):
        return None
    try:
        return await fetcher(channel_id)
    except Exception:
        log.exception("No se pudo resolver el canal de arranque %s", channel_id)
        return None


async def _read_recent_history(channel, limit=50):
    """Lee el historial reciente de un canal soportando dobles de prueba."""
    history = []
    result = channel.history(limit=limit)
    if asyncio.iscoroutine(result):
        result = await result
    async for message in result:
        history.append(message)
    return history


async def seed_last_human_activity(
    discord_client,
    *,
    channel_id,
    session,
    build_ctx,
    timers=None,
    dispatcher=None,
    run_turn=None,
    tracker=None,
    policy_loader=load_policy,
    clock=time.time,
):
    """Decide y siembra el estado conversacional inicial del canal.

    - Con mensaje humano pendiente: entra en Activa y responde solo a ese
      mensaje con el modo de conversación activa.
    - Sin pendiente válido: entra en Activa y arma la ventana de inactividad,
      de modo que el canal queda activo durante ``active_idle_seconds``.

    La ventana usa la misma variable que el retiro normal
    (``AIRI_SPECTATOR_ACTIVE_IDLE_SECONDS``) y se rearma con cada mensaje
    humano desde el handler de Discord. Con el modo espectador desactivado,
    o con una ventana <= 0, no se fuerza el estado Activa.
    """
    if session is None:
        return

    try:
        policy = policy_loader()
    except Exception:
        log.exception("No se pudo cargar la política del modo espectador")
        return
    if policy is None or not getattr(policy, "enabled", False):
        return

    window = float(getattr(session, "active_idle_seconds", 0.0) or 0.0)
    can_activate = window > 0.0 and timers is not None and dispatcher is not None

    channel = await _resolve_startup_channel(discord_client, channel_id)
    if channel is None:
        # Aun sin objeto canal podemos activar: el temporizador usa el id.
        if can_activate:
            session.enter_active(channel_id, now=clock())
            arm_active_timer(
                registry=session,
                timers=timers,
                dispatcher=dispatcher,
                channel_id=channel_id,
                timeout=window,
                clock=clock,
            )
        return

    target_channel_id = getattr(channel, "id", channel_id)

    try:
        history = await _read_recent_history(channel)
    except Exception:
        log.exception("No se pudo leer el historial de arranque del canal %s", target_channel_id)
        history = []

    if tracker is None:
        tracker = getattr(discord_client, "_pending_message_tracker", None)
    if tracker is None:
        tracker = PendingMessageTracker()

    user = getattr(discord_client, "user", None)
    bot_id = int(getattr(user, "id", 0) or 0)
    try:
        pending = tracker.find_pending_message(
            history,
            bot_id=bot_id,
            max_age=AIRI_SPECTATOR_PENDING_MAX_AGE_SECONDS,
            now=clock(),
        )
    except Exception:
        log.exception("No se pudo buscar el mensaje pendiente de arranque")
        pending = None

    if pending is not None:
        epoch = _epoch(getattr(pending, "created_at", None))
        if epoch > 0:
            if can_activate:
                session.record_human_activity(target_channel_id, now=epoch)
                session.enter_active(target_channel_id, now=clock())
            log.info(
                "Mensaje pendiente encontrado en canal %s (id=%s); "
                "iniciando respuesta dirigida",
                target_channel_id,
                getattr(pending, "id", ""),
            )
            pending_author = getattr(pending, "author", None)
            if pending_author is None or getattr(pending_author, "bot", False):
                pending_author = type(
                    "SyntheticUser", (), {"id": 0, "display_name": "usuario", "bot": False}
                )()
            pending_text = (getattr(pending, "content", "") or "").strip()
            if not pending_text:
                pending_text = "(mensaje sin texto)"
            runner = run_turn or turn.run_user_turn
            try:
                await runner(
                    build_ctx(channel, tracker),
                    channel,
                    pending_author,
                    [(pending_author, pending_text)],
                    reply_target=pending,
                    kind="active",
                    suppress_affinity=True,
                    consumed_message_ids=[getattr(pending, "id", None)],
                )
            except Exception:
                log.exception("Fallo la respuesta al mensaje pendiente")
            finally:
                if (
                    can_activate
                    and session.state(target_channel_id) == ConversationState.ACTIVE
                ):
                    arm_active_timer(
                        registry=session,
                        timers=timers,
                        dispatcher=dispatcher,
                        channel_id=target_channel_id,
                        timeout=window,
                        clock=clock,
                    )
            return

    if can_activate:
        session.enter_active(target_channel_id, now=clock())
        arm_active_timer(
            registry=session,
            timers=timers,
            dispatcher=dispatcher,
            channel_id=target_channel_id,
            timeout=window,
            clock=clock,
        )


def create_client(
    *,
    build_ctx,
    registry,
    channel_id,
    on_ready_extra=None,
    manual_shutdown=None,
    pending_state=None,
):
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    debounce = _Debouncer()
    dispatcher = ChannelDispatcher()
    timers = {}
    pending_message_tracker = PendingMessageTracker(state=pending_state)
    shutdown = {"started": False, "phase": "running"}
    coordinated = os.getenv("AIRI_COORDINATED", "0").lower() in ("1", "true", "yes")
    worker = None
    client._spectator_timers = timers
    client._spectator_dispatcher = dispatcher
    client._pending_message_tracker = pending_message_tracker

    async def _resolve_channel(target_id=None):
        target = channel_id if target_id is None else target_id
        try:
            target = int(target)
        except (TypeError, ValueError):
            pass
        getter = getattr(client, "get_channel", None)
        channel = getter(target) if getter is not None else None
        if channel is None:
            fetcher = getattr(client, "fetch_channel", None)
            if fetcher is not None:
                try:
                    channel = await fetcher(target)
                except Exception:
                    channel = None
        return channel

    def _wire_shutdown(ctx):
        """Conecta la decisión de Airi con el cierre global del cliente."""
        ctx.is_shutting_down = lambda: bool(shutdown["started"])

        async def request_shutdown(reason, user_id=None, correlation_id=None):
            if shutdown["started"]:
                log.info("Cierre ya en curso; se ignora la solicitud duplicada")
                return
            shutdown["started"] = True
            shutdown["phase"] = "closing"
            clean_reason = str(reason or "").strip()[:300]
            requested_at = time.time()
            log.info(f"{character_name()} decide desconectarse: %s", clean_reason)

            persistence = getattr(ctx, "persistence", None)
            if persistence is not None:
                async with (getattr(ctx, "commit_lock", None) or nullcontext()):
                    try:
                        with persistence.transaction():
                            ctx.state.world["last_shutdown"] = {
                                "kind": "self",
                                "reason": clean_reason,
                                "user_id": (
                                    str(user_id) if user_id is not None else ""
                                ),
                                "origin": "model",
                                "correlation_id": str(correlation_id or ""),
                                "requested_at": requested_at,
                                "updated_at": requested_at,
                                "status": "closing",
                                "context_delivered": False,
                            }
                            ctx.state.save_world()
                    except Exception:
                        log.exception("No se pudo guardar el motivo del cierre")

            def record_shutdown_status(status):
                if persistence is None:
                    return
                try:
                    with persistence.transaction():
                        entry = ctx.state.world.get("last_shutdown")
                        if not isinstance(entry, dict):
                            entry = {
                                "kind": "self",
                                "reason": clean_reason,
                                "origin": "model",
                                "correlation_id": str(correlation_id or ""),
                                "requested_at": requested_at,
                            }
                        entry["status"] = status
                        entry["updated_at"] = time.time()
                        ctx.state.world["last_shutdown"] = entry
                        ctx.state.save_world()
                except Exception:
                    log.exception("No se pudo registrar el resultado del cierre")

            async def close_after_reply():
                # Deja terminar el envío de la despedida antes de cerrar.
                await asyncio.sleep(0.5)
                channel = await _resolve_channel(getattr(ctx, "channel_id", None))
                if channel is not None:
                    try:
                        await channel.send(
                            embed=embeds.disconnecting_embed(clean_reason)
                        )
                    except Exception:
                        log.exception("No se pudo enviar el aviso de desconexión")
                for task in list(timers.values()):
                    task.cancel()
                timers.clear()
                try:
                    await discord.Client.close(client)
                except Exception:
                    log.exception("Discord no pudo cerrar la conexión")
                    shutdown["phase"] = "failed"
                    shutdown["started"] = False
                    record_shutdown_status("failed")
                    return
                try:
                    closed = bool(client.is_closed())
                except Exception:
                    closed = True
                if closed:
                    shutdown["phase"] = "closed"
                    record_shutdown_status("confirmed")
                else:
                    shutdown["phase"] = "failed"
                    shutdown["started"] = False
                    record_shutdown_status("failed")
                    log.error(f"El cierre no se confirmó; {character_name()} sigue disponible")

            asyncio.create_task(close_after_reply())

        ctx.request_shutdown = request_shutdown
        ctx.acknowledge_reconnect_context = lambda: acknowledge_reconnect_context(ctx)

    def _persist_manual_shutdown(status):
        """Guarda/actualiza la entrada de cierre manual en world."""
        ms = manual_shutdown or {}
        state = ms.get("state")
        if state is None:
            return
        persistence = ms.get("persistence")
        now = time.time()

        def build_entry():
            return {
                "kind": "self",
                "reason": str(ms.get("reason") or "").strip()[:300],
                "user_id": "",
                "origin": "manual",
                "correlation_id": "",
                "requested_at": now,
                "updated_at": now,
                "status": status,
                "context_delivered": False,
            }

        def next_entry(current):
            if status == "closing" or not isinstance(current, dict):
                return build_entry()
            current["status"] = status
            current["updated_at"] = now
            return current

        if persistence is None:
            try:
                entry = next_entry(state.world.get("last_shutdown"))
                state.world["last_shutdown"] = entry
                state.save_world()
            except Exception:
                log.exception("No se pudo registrar el cierre manual")
            return
        try:
            with persistence.transaction():
                entry = next_entry(state.world.get("last_shutdown"))
                state.world["last_shutdown"] = entry
                state.save_world()
        except Exception:
            log.exception("No se pudo registrar el cierre manual")

    async def manual_close():
        """Ctrl+C: aviso en el canal con motivo, estado y cierre del cliente."""
        ms = manual_shutdown or {}
        reason = str(ms.get("reason") or "").strip()[:300]
        _persist_manual_shutdown("closing")
        channel = await _resolve_channel(channel_id)
        if channel is not None:
            try:
                await channel.send(embed=embeds.disconnecting_embed(reason))
            except Exception:
                log.exception("No se pudo enviar el aviso de desconexión manual")
        for task in list(timers.values()):
            task.cancel()
        timers.clear()
        try:
            await client.close()
        except Exception:
            log.exception("Discord no pudo cerrar la conexión")
            shutdown["phase"] = "failed"
            shutdown["started"] = False
            _persist_manual_shutdown("failed")
            return
        shutdown["phase"] = "closed"
        _persist_manual_shutdown("confirmed")

    def install_manual_shutdown_hook():
        """Sustituye el Ctrl+C de discord.py por un cierre con despedida."""
        ms = manual_shutdown
        if ms is None:
            return
        loop = asyncio.get_running_loop()

        def trigger():
            if shutdown["started"]:
                log.info("Cierre ya en curso; se ignora Ctrl+C duplicado")
                return
            shutdown["started"] = True
            shutdown["phase"] = "closing"
            log.info("Cierre manual (Ctrl+C): %s", str(ms.get("reason") or ""))
            asyncio.ensure_future(manual_close())

        client.manual_shutdown_trigger = trigger
        try:
            loop.add_signal_handler(signal.SIGINT, trigger)
        except (NotImplementedError, AttributeError):
            # Windows/otro backend: no hay gestión fiable de señales en el loop.
            log.warning(
                "SIGINT no se puede interceptar en este backend: Ctrl+C "
                "apagará sin aviso de despedida en el canal"
            )

    def _reset_conversation(ctx, ch_id, author_id):
        debounce.reset(ch_id, author_id)
        ctx.state.histories.pop(ch_id, None)
        buffer = getattr(ctx, "passive_buffer", None)
        if buffer is not None:
            buffer.clear(ch_id)

    @client.event
    async def on_ready():
        nonlocal worker
        log.info("Bot conectado como %s", client.user)
        log.info("Canal autorizado: %s", channel_id)
        if coordinated:
            if worker is None:
                from airi.coordinator.worker import DiscordWorker
                worker = DiscordWorker(client, build_ctx, registry, channel_id, _wire_shutdown)
                worker.task = asyncio.create_task(worker.run())
                client._coordinator_worker = worker
            return
        if not shutdown["started"]:
            channel = await _resolve_channel()
            if channel is not None:
                try:
                    await channel.send(embed=embeds.connected_embed())
                except Exception:
                    log.exception("No se pudo enviar el aviso de conexión")
            if on_ready_extra is not None:
                try:
                    await on_ready_extra(client)
                except Exception:
                    log.exception("La tarea de arranque posterior falló")
            install_manual_shutdown_hook()

    @client.event
    async def on_message(message):
        if coordinated:
            if worker is not None:
                await worker.observe(message)
            return
        with tracked_interaction() as tracker:
            if shutdown["started"]:
                return

            if message.author.bot or message.channel.id != channel_id:
                tracker.module_result(
                    "discord_input", "skipped", reason_code="message_filtered"
                )
                return

            content = message.content.strip()
            if not content:
                tracker.module_result(
                    "discord_input", "skipped", reason_code="message_filtered"
                )
                return

            tracker.module_result("discord_input", "activated")

            ctx = build_ctx(message.channel, pending_message_tracker)
            _wire_shutdown(ctx)
            ctx.reset_conversation = (
                lambda ch_id, author_id: _reset_conversation(ctx, ch_id, author_id)
            )

            if ctx.expire_stale_dates():
                await message.channel.send(
                    "🌙 «Vaya, se me ha ido el tiempo... la cita termina aquí. "
                    "*se despide con la mano*»"
                )

            handler = registry.match(content)
            if handler is not None:
                tracker.module_result(
                    "commands", "activated", reason_code="command_matched"
                )
                await handler(ctx, message)
                tracker.module_result(
                    "commands", "activated", reason_code="command_handled"
                )
                return

            spectator_policy = getattr(ctx, "spectator_policy", None)
            passive_buffer = getattr(ctx, "passive_buffer", None)
            spectator_session = getattr(ctx, "spectator_session", None)
            session_state = (
                spectator_session.state(message.channel.id)
                if spectator_session is not None
                else None
            )
            session_state_name = getattr(session_state, "name", str(session_state))
            if (
                spectator_policy is not None
                and spectator_policy.enabled
                and passive_buffer is not None
                and session_state_name == "SPECTATING"
            ):
                passive_buffer.append(
                    message.channel.id,
                    str(message.author.id),
                    getattr(message.author, "display_name", ""),
                    content,
                    message_id=str(getattr(message, "id", "")),
                )

            owner_id, _owner_session = ctx.busy_date_owner(exclude_id=message.author.id)
            if owner_id is not None:
                tracker.module_result(
                    "commands", "activated", reason_code="owner_busy"
                )
                await ctx.notify_busy(message.channel, message.author)
                return

            if spectator_session is not None and spectator_policy is not None and spectator_policy.enabled:
                spectator_session.record_human_activity(message.channel.id)
                st_name = spectator_session.state(message.channel.id).name
                if st_name == "ACTIVE":
                    arm_active_timer(
                        registry=spectator_session,
                        timers=timers,
                        dispatcher=dispatcher,
                        channel_id=message.channel.id,
                    )
                elif st_name == "SPECTATING":
                    key = (str(message.channel.id), "proactive")
                    old = timers.pop(key, None)
                    if old is not None:
                        old.cancel()
                    timeout = getattr(
                        spectator_session, "proactive_idle_seconds", 21600.0
                    )

                    async def _proactive_timer():
                        try:
                            await asyncio.sleep(float(timeout))
                        except asyncio.CancelledError:
                            return
                        now = time.time()

                        async def _job():
                            reg = spectator_session
                            if not reg.should_fire_proactive(message.channel.id, now):
                                return
                            channel = await _resolve_channel(message.channel.id)
                            if channel is None:
                                return
                            synthetic = type(
                                "SyntheticUser", (), {"id": 0, "display_name": f"{character_name()}", "bot": False}
                            )()
                            try:
                                await turn.run_user_turn(
                                    ctx,
                                    channel,
                                    synthetic,
                                    [(synthetic, "")],
                                    reply_target=None,
                                    kind="proactive",
                                    suppress_affinity=True,
                                )
                            except Exception:
                                log.exception("Fallo el turno proactivo")

                        try:
                            await dispatcher.submit(message.channel.id, _job)
                        except Exception:
                            log.exception("No se pudo procesar el despertar proactivo")

                    timers[key] = asyncio.create_task(_proactive_timer())

            key = (message.channel.id, message.author.id)
            seq = debounce.next_seq(key)
            debounce.add(
                key, (message.author, content), message_id=str(getattr(message, "id", ""))
            )
            await asyncio.sleep(ctx.debounce_seconds)
            if debounce.current_seq(key) != seq:
                tracker.module_result(
                    "debounce", "activated", reason_code="debounce_replaced"
                )
                return
            merged, merged_ids = debounce.pop(key)
            if not merged:
                tracker.module_result(
                    "debounce", "activated", reason_code="debounce_replaced"
                )
                return

            if spectator_policy is None or not spectator_policy.enabled or spectator_session is None:
                await dispatcher.submit(
                    message.channel.id,
                    lambda: turn.run_user_turn(
                        ctx, message.channel, message.author, merged,
                        reply_target=message,
                        consumed_message_ids=merged_ids,
                    ),
                    message_ids=[getattr(message, "id", None)],
                )
                tracker.module_result("queue", "activated", reason_code="normal_turn")
                return

            st_name = spectator_session.state(message.channel.id).name
            if st_name in ("ACTIVE", "WAKING"):
                async def _guarded_active_job():
                    current = spectator_session.state(message.channel.id).name
                    if current in ("ACTIVE", "WAKING"):
                        await turn.run_user_turn(
                            ctx,
                            message.channel,
                            message.author,
                            merged,
                            reply_target=message,
                            kind="active",
                            consumed_message_ids=merged_ids,
                        )
                        return
                    if current == "SPECTATING":
                        decision = await _evaluate_spectator_event(ctx, message, merged)
                        if not decision.proceed:
                            _t = current_tracker()
                            if _t is not None:
                                _t.module_result(
                                    "spectator", "skipped",
                                    reason_code="spectator_not_proceeding",
                                )
                            if passive_buffer is not None:
                                passive_buffer.append(
                                    message.channel.id,
                                    str(message.author.id),
                                    getattr(message.author, "display_name", ""),
                                    "\n".join(part for _, part in merged),
                                    message_id=(
                                        str(merged_ids[-1]) if merged_ids else ""
                                    ),
                                )
                            return
                        snapshot_ids = {"", *merged_ids}
                        entries = passive_buffer.snapshot(
                            message.channel.id, exclude_ids=snapshot_ids
                        ) if passive_buffer is not None else []
                        entry_dicts = [
                            {
                                "author_id": e.author_id,
                                "author_name": e.author_name,
                                "content": e.content,
                                "message_id": e.message_id,
                                "ts": e.ts,
                            }
                            for e in entries
                        ]
                        handoff = decision.reason == "handoff"
                        await turn.run_user_turn(
                            ctx,
                            message.channel,
                            message.author,
                            merged,
                            reply_target=message,
                            kind="spectator",
                            spectator_reason=decision.reason,
                            spectator_snapshot=tuple(entry_dicts),
                            spectator_guaranteed=decision.guaranteed,
                            spectator_handoff=handoff,
                            spectator_trigger_ids=merged_ids,
                        )

                await dispatcher.submit(
                    message.channel.id,
                    _guarded_active_job,
                    message_ids=[getattr(message, "id", None)],
                )
                tracker.module_result("queue", "activated", reason_code="active_turn")
                return

            decision = await _evaluate_spectator_event(ctx, message, merged)
            if not decision.proceed:
                tracker.module_result(
                    "spectator", "skipped", reason_code="spectator_not_proceeding"
                )
                return

            snapshot_ids = {"", *merged_ids}
            entries = passive_buffer.snapshot(
                message.channel.id, exclude_ids=snapshot_ids
            ) if passive_buffer is not None else []
            entry_dicts = [
                {
                    "author_id": e.author_id,
                    "author_name": e.author_name,
                    "content": e.content,
                    "message_id": e.message_id,
                    "ts": e.ts,
                }
                for e in entries
            ]
            handoff = decision.reason == "handoff"
            await dispatcher.submit(
                message.channel.id,
                lambda: turn.run_user_turn(
                    ctx,
                    message.channel,
                    message.author,
                    merged,
                    reply_target=message,
                    kind="spectator",
                    spectator_reason=decision.reason,
                    spectator_snapshot=tuple(entry_dicts),
                    spectator_guaranteed=decision.guaranteed,
                    spectator_handoff=handoff,
                    spectator_trigger_ids=merged_ids,
                ),
                message_ids=[getattr(message, "id", None)],
            )
            tracker.module_result("queue", "activated", reason_code="spectator_turn")

    async def _evaluate_spectator_event(ctx, message, merged):
        """Señales locales del modo espectador para el mensaje actual."""
        policy = ctx.spectator_policy
        gate = getattr(ctx, "spectator_gate", None)

        merged_text = "\n".join(part for _, part in merged)
        airi_user = getattr(client, "user", None)
        airi_id = str(getattr(airi_user, "id", "") or "")
        airi_name = str(
            getattr(airi_user, "name", "") or getattr(airi_user, "display_name", "")
        )
        reply_to_airi = await _is_reply_to_airi(message)
        mention = spectator.mention_signals(
            merged_text, airi_id, airi_name, reply_to_airi
        )
        topic_pattern = spectator.build_topic_matcher(
            spectator.positive_taste_terms(ctx.state.world.get("preferences"))
        )
        buffer = getattr(ctx, "passive_buffer", None)
        recent_texts = [merged_text]
        if buffer is not None:
            recent_entries = buffer.snapshot(message.channel.id)
            recent_texts.extend(entry.content for entry in recent_entries)
        topic = any(
            spectator.topic_eligible(topic_pattern, text)
            for text in dict.fromkeys(recent_texts)
            if text
        )
        affinity = spectator.affinity_eligible(
            ctx.state.entry_points(message.author.id),
            policy.affinity_threshold,
        )
        affine_signals = (mention, topic, affinity)
        log.debug(
            "Modo espectador señales: mention=%s topic=%s affinity=%s",
            *affine_signals,
        )
        pending_handoff = (
            gate.has_pending_handoff(message.channel.id, message.author.id)
            if gate is not None
            else False
        )
        return spectator_policy_module.evaluate_event(
            policy=policy,
            gate=gate,
            channel_id=message.channel.id,
            author_id=message.author.id,
            mention=mention,
            topic=topic,
            affinity=affinity,
            handoff=pending_handoff,
        )

    async def _is_reply_to_airi(message):
        """True si el mensaje responde a un mensaje de Airi (best-effort)."""
        reference = getattr(message, "reference", None)
        if reference is None:
            return False
        cached = getattr(reference, "cached_message", None)
        if cached is not None:
            author = getattr(cached, "author", None)
            airi = getattr(client, "user", None)
            return bool(airi is not None and getattr(author, "id", None) == airi.id)
        # Sin caché del mensaje citado no se puede confirmar el autor; el modo
        # espectador no adivina: se evalúan las otras señales.
        return False

    if coordinated:
        original_close = client.close
        async def coordinated_close():
            if worker is not None:
                await worker.close()
            await original_close()
        client.close = coordinated_close
    return client


def build_date_glue(state, *, llm_base_url, request_timeout):
    """Pegamentos Discord↔dominio para citas, regalos y diario.

    Devuelve un `SimpleNamespace` con los callables que `BotContext` inyecta.
    Vive fuera de `run_bot` para poder testearlo sin levantar el bot (basta un
    `AppState` y, para las llamadas al modelo, un `session` doble).

    La migración hexagonal dejó estos métodos como stubs vacíos en `run_bot`,
    lo que rompía `!cita` (TypeError por firma) y `!regalo`.
    """
    from airi.adapters.discord_notifier import DiscordNotifier
    from airi.adapters.http_llm import build_llm
    from airi.domain.affinity import (
        affinity_level,
        affinity_summary,
        clamp_delta,
        is_winner,
    )
    from airi.domain.constants import (
        DATE_BUSY_NOTICE_COOLDOWN,
        DATE_QUESTION_DELTA_MAX,
        DATE_SCENE_MAX_TOKENS,
        DATE_SCENES,
        DIARY_REFLECTION_MIN_INTERVAL,
        LLM_REASONING_PRESETS,
    )
    from airi.domain.date_invitation import parse_date_invitation_decision
    from airi.domain.dates import (
        date_expired,
        date_seconds_left,
        question_failed_hard,
        question_option,
        roll_question,
    )
    from airi.domain.diary import add_diary_entry, new_diary_entry
    from airi.domain.llm_output import extract_json_object, parse_scene_list
    from airi.domain.prompts import (
        DATE_INVITATION_DECISION_PROMPT,
        DATE_INVITATION_DECISION_SCHEMA,
        GIFT_JUDGE_PROMPT,
        GIFT_JUDGE_SCHEMA,
        SCENE_PROPOSAL_PROMPT,
        SCENE_PROPOSAL_SCHEMA,
        SYSTEM_PROMPT,
        affinity_prompt_section,
        preferences_prompt_section,
        relationship_status_section,
        romantic_relationship_section,
    )
    from airi.domain.relationship_claims import (
        relationship_claim_problem,
        soften_relationship_claims,
    )
    from airi.domain.text_filters import clean_reply
    from airi.services.date_service import DateService
    from airi.services.relationships import RelationshipService

    busy_notice_at = {}  # uid -> timestamp del último aviso (anti-spam).
    relationships = RelationshipService(state)

    async def request_llama(session, messages, *, schema, max_tokens=None):
        llm = build_llm(session, timeout=request_timeout, base_url=llm_base_url)
        text, _meta = await llm.chat_with_meta(
            messages,
            schema=schema,
            max_tokens=max_tokens,
            reasoning_budget_tokens=LLM_REASONING_PRESETS["low"],
            strict_schema=True,
        )
        return text

    def fallback_scenes():
        """Escenas de reserva si el modelo no responde bien."""
        count = min(3, len(DATE_SCENES))
        return random.sample(list(DATE_SCENES), k=count)

    async def propose_scenes(session, user=None):
        """Pide a la IA 3-4 planes de cita; si falla, usa escenas de reserva."""
        who = state.display_name(user.id) if user is not None else "esa persona"
        messages = [
            {"role": "system", "content": SCENE_PROPOSAL_PROMPT},
            {"role": "user", "content": f"Propón planes de cita con {who}."},
        ]
        try:
            raw = await request_llama(
                session,
                messages,
                schema=SCENE_PROPOSAL_SCHEMA,
                max_tokens=DATE_SCENE_MAX_TOKENS,
            )
            parsed = extract_json_object(raw) if isinstance(raw, str) else None
            scenes = (
                parse_scene_list(parsed.get("scenes"))
                if isinstance(parsed, dict)
                else []
            )
            if scenes:
                return scenes
            log.warning(
                "El modelo no devolvió escenas válidas; uso escenas de reserva"
            )
        except Exception:
            log.exception("Error proponiendo escenas; uso escenas de reserva")
        return fallback_scenes()

    async def evaluate_date_invitation(session, user):
        """Decide si Airi acepta; errores o payloads inválidos fallan cerrados."""
        uid = user.id if user is not None else None
        display = state.display_name(uid) if uid is not None else "Alguien"
        points = state.entry_points(uid) if uid is not None else 0
        level_name = affinity_level(points)[0]
        affinity_desc = affinity_prompt_section(points, level_name, display)
        relationship_desc = relationship_status_section(
            state.world,
            state.users,
            user_id=uid,
            display_name=display,
            now=time.time(),
        )
        romantic_view = relationships.view(
            uid,
            turn_key=(
                f"date-invitation:{uid}:{int(time.time())}" if uid is not None else None
            ),
            channel_id=0,
        )
        romantic_view["allowed_refs"] = []
        romantic_desc = (
            romantic_relationship_section(romantic_view, display)
            if uid is not None else ""
        )
        messages = [
            {
                "role": "system",
                "content": (
                    SYSTEM_PROMPT
                    + affinity_desc
                    + relationship_desc
                    + romantic_desc
                    + DATE_INVITATION_DECISION_PROMPT
                ),
            },
            {
                "role": "user",
                "content": f"{display} te invita a una cita. Decide si quieres aceptar.",
            },
        ]
        try:
            raw = await request_llama(
                session,
                messages,
                schema=DATE_INVITATION_DECISION_SCHEMA,
                max_tokens=max(256, DATE_SCENE_MAX_TOKENS),
            )
            parsed = extract_json_object(raw) if isinstance(raw, str) else None
            decision = parse_date_invitation_decision(parsed)
            if decision is None:
                log.warning("El modelo devolvió una decisión de cita inválida")
            return decision
        except Exception:
            log.exception("Error evaluando invitación a cita")
            return None

    async def judge_gift(session, item, user, recent_gifts=None):
        """Airi juzga un regalo: su reacción y cuánta afinidad le llega.

        Devuelve (reply, delta, event) o None si el modelo falla. `delta` ya
        viene con el candado aplicado (0 si Airi no declara motivo).
        """
        uid = user.id if user is not None else None
        display = state.display_name(uid) if uid is not None else "Alguien"
        points = state.entry_points(uid) if uid is not None else 0
        level_name = affinity_level(points)[0]
        affinity_desc = affinity_prompt_section(points, level_name, display)
        relationship_desc = relationship_status_section(
            state.world,
            state.users,
            user_id=uid,
            display_name=display,
            now=time.time(),
        )
        prefs_desc = preferences_prompt_section(state.world)
        romantic_view = relationships.view(
            uid, turn_key=f"gift:{uid}:{int(time.time())}" if uid is not None else None,
            channel_id=0,
        )
        romantic_view["allowed_refs"] = []
        romantic_desc = romantic_relationship_section(
            romantic_view, display
        ) if uid is not None else ""
        recent = [str(g) for g in (recent_gifts or [])]
        recent_desc = ", ".join(recent) if recent else "(ninguno)"
        system_prompt = (
            SYSTEM_PROMPT
            + affinity_desc
            + relationship_desc
            + romantic_desc
            + prefs_desc
            + GIFT_JUDGE_PROMPT
        )
        user_message = (
            f"{display} te acaba de regalar «{item}». "
            f"Regalos recientes que ya te ha hecho: {recent_desc}. "
            f"Reacciona como {current_persona().name} y decide, con tu criterio, si el regalo mueve tu "
            "afinidad y cuánto."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        try:
            raw = await request_llama(
                session,
                messages,
                schema=GIFT_JUDGE_SCHEMA,
            )
        except Exception:
            log.exception(f"No se pudo consultar a {character_name()} sobre el regalo")
            return None
        parsed = extract_json_object(raw) if isinstance(raw, str) else None
        if not isinstance(parsed, dict):
            return None

        reply_raw = parsed.get("reply")
        reply = clean_reply(reply_raw) if isinstance(reply_raw, str) else ""
        if reply and uid is not None:
            stage = state.read_relationship(uid)["stage"]
            partner = is_winner(state.world, uid)
            if relationship_claim_problem(
                reply, stage=stage, partner_confirmed=partner
            ):
                reply = soften_relationship_claims(
                    reply, stage=stage, partner_confirmed=partner
                )
        delta_raw = parsed.get("affinity_delta", 0)
        if isinstance(delta_raw, bool) or not isinstance(delta_raw, (int, float)):
            delta = 0
        else:
            delta = int(delta_raw)
        delta = clamp_delta(delta)
        event_raw = parsed.get("affinity_event", "none")
        event = event_raw.strip()[:300] if isinstance(event_raw, str) else "none"
        if event.lower() in ("", "none", "ninguno", "null"):
            delta = 0
        log.info(
            f"{character_name()} juzga el regalo «%s»: delta %+d (motivo: %s)", item, delta, event
        )
        return reply, delta, event

    async def process_date_turn(
        channel,
        user,
        date_session,
        *,
        text,
        delta,
        points,
        date_decision,
        date_reason,
        last_chance_result,
        now,
        question=None,
        defer=False,
    ):
        """Avanza un turno de la cita y cierra si toca.

        Devuelve el evento del turno (ver airi.domain.dates.step_date). La
        lógica vive en `airi.services.date_service.DateService`.
        """
        service = DateService(state=state, notifier=DiscordNotifier(channel))
        args = (
            date_session,
        )
        kwargs = dict(
            user=user,
            text=text,
            delta=delta,
            points=points,
            date_decision=date_decision,
            date_reason=date_reason,
            last_chance_result=last_chance_result,
            now=now,
            question=question,
        )
        if defer:
            return service.process_turn_deferred(*args, **kwargs)
        return await service.process_turn(*args, **kwargs)

    def resolve_question(session, option_index):
        """Tira el dado de la alternativa elegida. Devuelve el resultado o None.

        El swing (`delta_up` / `delta_down`) lo decide la IA al escribir la
        pregunta; aquí solo se tira el dado y se acota el resultado.
        """
        option = question_option(session, option_index)
        if option is None:
            return None
        win, delta = roll_question(option, random)
        try:
            index = int(option_index)
        except (TypeError, ValueError):
            index = -1
        return {
            "index": index,
            "win": win,
            "delta": delta,
            "label": str(option.get("label", "") or ""),
            "action": str(option.get("action", "") or ""),
        }

    def apply_question_result(session, result, *, user_id=None, now=None):
        """Aplica el swing de la pregunta y deja la cita lista para continuar.

        Un fallo grave (desplome hasta el umbral) fuerza la crisis: la cita
        pasa a la última oportunidad, que es donde el jugador puede
        reconquistarla.
        """
        if now is None:
            now = time.time()
        delta = int(result.get("delta", 0) or 0)
        session["question_pending"] = False
        session["question_result"] = {
            "index": result.get("index"),
            "win": bool(result.get("win")),
            "delta": delta,
            "label": result.get("label", ""),
            "at": now,
        }
        if delta and user_id is not None:
            # El swing de la pregunta es más grande que el cambio normal: se
            # aplica con su propio tope (±DATE_QUESTION_DELTA_MAX).
            state.apply_affinity(
                user_id,
                delta,
                now=now,
                delta_max=DATE_QUESTION_DELTA_MAX,
                delta_min=-DATE_QUESTION_DELTA_MAX,
            )
            state.save_affinity()
        if question_failed_hard(delta):
            session["force_crisis"] = True
        state.save_dates()
        log.info(
            "Pregunta decisiva respondida: acierto=%s delta=%+d", result.get("win"), delta
        )
        return session

    def expire_question(uid, *, notify_channel=None):
        """Cancela la pregunta pendiente (se agotó el tiempo o la cita)."""
        session = state.dates.get(str(uid))
        if not isinstance(session, dict):
            return False
        if not session.get("question_pending"):
            return False
        session["question_pending"] = False
        state.save_dates()
        log.info("La pregunta decisiva de %s caducó sin respuesta", uid)
        return True

    def _finish_date(user_id, session, event, *, now):
        """Cierra la cita: registra el resultado en el diario y la elimina."""
        DateService(state=state).finish_date(user_id, session, event, now=now)

    def expire_stale_dates(now=None):
        """Cierra las citas que superaron su duración máxima.

        Devuelve la lista de uids cerrados. Se llama al principio de
        `on_message` para que una cita abandonada nunca bloquee el canal.
        """
        if now is None:
            now = time.time()
        expired = []
        for uid, session in list(state.dates.items()):
            if date_expired(session, now):
                expired.append(uid)
                _finish_date(uid, session, "ending", now=now)
        if expired:
            log.info("Citas caducadas por tiempo: %s", ", ".join(expired))
        return expired

    def busy_date_owner(exclude_id=None):
        """Devuelve (uid, session) de la cita activa de OTRO usuario.

        Antes de buscar, expira las citas caducadas para no bloquear el canal.
        """
        expire_stale_dates()
        exclude = None if exclude_id is None else str(exclude_id)
        for uid, session in state.dates.items():
            if not isinstance(session, dict):
                continue
            if session.get("state") == "closed":
                continue
            if exclude is not None and str(uid) == exclude:
                continue
            return str(uid), session
        return None, None

    def date_busy_text(owner_id, owner_session, now=None):
        """Mensaje de sistema que anuncia que Airi está en una cita."""
        if now is None:
            now = time.time()
        name = state.display_name(owner_id)
        seconds = date_seconds_left(owner_session, now)
        if seconds < 60:
            when = "en menos de 1 min"
        else:
            when = f"en ~{int((seconds + 59) // 60)} min"
        return (
            f"🌸 **{character_name()} está en una cita ahora mismo.** Está con **{name}**. "
            f"Su cita termina {when}. Vuelve un poco más tarde para hablar con ella~"
        )

    async def notify_busy(channel, user, now=None):
        """Avisa de que Airi está ocupada, respetando un cooldown por usuario."""
        if now is None:
            now = time.time()
        uid = user.id
        last = busy_notice_at.get(uid, 0.0)
        if now - last < DATE_BUSY_NOTICE_COOLDOWN:
            return
        busy_notice_at[uid] = now
        owner_id, session = busy_date_owner(exclude_id=uid)
        if owner_id is None:
            return
        await channel.send(date_busy_text(owner_id, session, now))

    def add_diary_reflection(
        user_id, text, now=None, min_interval=DIARY_REFLECTION_MIN_INTERVAL
    ):
        """Guarda una reflexión de Airi en 1ª persona. Devuelve True si se guardó."""
        text = clean_reply(text).strip()[:200].strip()
        if not text:
            return False
        key = str(user_id)
        recent = [
            e
            for e in state.diary[-20:]
            if isinstance(e, dict)
            and e.get("kind") == "reflection"
            and str(e.get("user_id")) == key
        ]
        lower = text.lower()
        if any(lower == str(e.get("text", "")).lower() for e in recent):
            log.info("Reflexión duplicada descartada para %s", user_id)
            return False
        now = time.time() if now is None else now
        if recent and now - float(recent[-1].get("ts", 0.0) or 0.0) < min_interval:
            return False
        entry = new_diary_entry(
            "reflection",
            user_id,
            state.display_name(user_id),
            text,
            now,
            season=int(state.world.get("season", 1) or 1),
        )
        if add_diary_entry(state.diary, entry):
            state.save_diary()
            log.info("Reflexión guardada para %s: %r", user_id, text)
            return True
        return False

    def affinity_footer_text(user_id, display_name):
        points, level_name, progress = affinity_summary(state.entry_points(user_id))
        return (
            f"💛 Afinidad de {display_name}: {points} pts · "
            f"{level_name} · {progress}"
        )

    return SimpleNamespace(
        evaluate_date_invitation=evaluate_date_invitation,
        propose_scenes=propose_scenes,
        judge_gift=judge_gift,
        process_date_turn=process_date_turn,
        resolve_question=resolve_question,
        apply_question_result=apply_question_result,
        expire_question=expire_question,
        busy_date_owner=busy_date_owner,
        notify_busy=notify_busy,
        date_busy_text=date_busy_text,
        expire_stale_dates=expire_stale_dates,
        add_diary_reflection=add_diary_reflection,
        affinity_footer_text=affinity_footer_text,
    )


def run_bot(argv=None):
    """Inicia el bot de Discord.

    Construye la aplicación modular hexagonal y ejecuta el cliente de Discord.
    """
    import asyncio
    import logging
    import os

    import aiohttp

    from airi.adapters.brave_search import BraveSearchClient
    from airi.adapters.discord_notifier import DiscordNotifier
    from airi.adapters.http_llm import DEFAULT_MODEL, LlmConfig, build_llm
    from airi.adapters.instance_lock import (
        InstanceAlreadyRunningError,
        InstanceLock,
    )
    from airi.adapters.nekosbest import NekosBestProvider
    from airi.adapters.state_store import StateStore
    from airi.config import Settings
    from airi.discord_bot import turn as discord_turn
    from airi.discord_bot.commands import build_registry
    from airi.discord_bot.context import BotContext
    from airi.domain.affinity import (
        AFFINITY_DELTA_MAX,
        AFFINITY_DELTA_MIN,
        apply_affinity_delta,
        apply_winner_lock,
    )
    from airi.domain.state_schema import CURRENT_SCHEMA_VERSION
    from airi.logging_setup import install_correlation_format
    from airi.observability.jsonl_events import install_jsonl_logging
    from airi.observability.trace_store import TraceStore
    from airi.services.bootstrap import BootstrapError, bootstrap_state
    from airi.services.conversation import ConversationService
    from airi.services.migration import LegacyMigrator
    from airi.services.publication import PublicationResumer
    from airi.services.retention import RetentionService
    from airi.services.season_archive import SeasonArchiver
    from airi.services.self_service import SelfService
    from airi.services.turn_journal import TurnJournal

    log = logging.getLogger(__name__)

    # Configuración
    persona = current_persona()  # validate before connecting to Discord
    TOKEN = os.getenv("DISCORD_TOKEN")
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
    LLM_CFG = LlmConfig.from_env()
    LLM_BASE_URL = LLM_CFG.base_url
    BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
    NEKOSBEST_CONTACT = os.getenv("NEKOSBEST_CONTACT", "")
    GIF_TIMEOUT = int(os.getenv("GIF_TIMEOUT", "20"))
    try:
        REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "300"))
    except (ValueError, TypeError):
        log.warning("REQUEST_TIMEOUT tiene valor inválido, usando 300")
        REQUEST_TIMEOUT = 300
    MAX_WEB_RESULTS = int(os.getenv("MAX_WEB_RESULTS", "5"))
    DEBOUNCE_SECONDS = float(os.getenv("DEBOUNCE_SECONDS", "3"))
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
    CONFESS_THRESHOLD = int(os.getenv("CONFESS_THRESHOLD", "100"))
    manual_shutdown_reason = (
        os.getenv("AIRI_SHUTDOWN_REASON", "").strip()
        or (f"😴 {character_name()} se fue a dormir..." if persona.legacy else persona.disconnected)
    )[:300]

    # Datos globales
    commit_lock = asyncio.Lock()

    # Settings y almacén
    settings = Settings.from_env()
    trace_store = TraceStore(settings.trace_dir, settings.trace_keep_last)
    install_correlation_format()
    install_jsonl_logging()
    if os.getenv("AIRI_COORDINATED") == "1":
        from airi.coordinator.worker import install_worker_logging

        install_worker_logging()

    run_lock = InstanceLock(settings.lock_path)
    try:
        run_lock.acquire()
    except InstanceAlreadyRunningError as exc:
        log.error("%s", exc)
        return 1

    try:
        store = StateStore(settings.data_dir)
        migrator = LegacyMigrator(settings.data_dir, store)
        boot = bootstrap_state(store=store, migrator=migrator)
    except BootstrapError as exc:
        log.error("Estado bloqueado; el bot no puede arrancar: %s", exc)
        if exc.quarantine_path:
            log.error("Copia en cuarentena: %s", exc.quarantine_path)
        run_lock.release()
        return 1

    state = boot.state
    persistence = boot.persistence
    state.traces = trace_store
    if state.clean_legacy_self_discoveries():
        log.info("Se limpiaron notas genéricas y eventos legacy de autodescubrimiento")
    if boot.recovered:
        log.warning("Estado recuperado desde la copia de seguridad")
    if boot.migration is not None:
        log.info(
            "Migración de datos heredados: %s (origen %s)",
            boot.migration.status.value,
            boot.migration.source_hash[:12],
        )

    state.apply_affinity_fn = lambda uid, delta, now=None, delta_max=None, delta_min=None: (
        lambda entry: apply_affinity_delta(
            entry,
            delta,
            now or time.time(),
            delta_max if delta_max is not None else AFFINITY_DELTA_MAX,
            delta_min if delta_min is not None else AFFINITY_DELTA_MIN,
        )
    )(state.affinity_entry(uid))

    # Alias de compatibilidad para el pegamento de citas/coronación.
    world_data = state.world
    affinity_data = state.affinity
    users_data = state.users

    turn_journal = TurnJournal(state, persistence=persistence)
    try:
        with persistence.transaction():
            state.decay_self(now=time.time())
    except Exception:
        log.exception("No se pudo aplicar la deriva de identidad al arrancar")

    # Perfil canónico de gustos: AIRI_PROFILE (JSON) prevalece si es válida.
    try:
        if apply_stable_profile(state, load_stable_profile()):
            log.info("Perfil canónico de gustos aplicado desde AIRI_PROFILE")
    except Exception:
        log.exception("No se pudo aplicar el perfil canónico de AIRI_PROFILE")

    reflection_inflight: set[str] = set()

    async def maybe_reflect(user_id, now):
        """Reflexión automática en segundo plano, sin retrasar la respuesta."""
        key = str(user_id)
        if key in reflection_inflight:
            return
        reflection_inflight.add(key)
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                llm = build_llm(session, timeout=REQUEST_TIMEOUT, base_url=LLM_BASE_URL)
                service = SelfService(
                    llm=llm,
                    state=state,
                    clock=time.time,
                    lock=commit_lock,
                    persistence=persistence,
                )
                outcome = await service.reflect(
                    user_id, now=now, trigger="interaction"
                )
                if outcome.changed:
                    log.info(
                        "Reflexión automática: discovery=%s self_change=%s",
                        bool(outcome.discovery),
                        outcome.self_entry is not None,
                    )
                return outcome
        except Exception:
            log.exception("La reflexión automática falló")
            return None
        finally:
            reflection_inflight.discard(key)

    season_archiver = SeasonArchiver(settings.data_dir)
    retention = RetentionService(
        settings.data_dir,
        season_limit=settings.season_retention,
        backup_limit=settings.backup_retention,
    )

    # Estado social del modo espectador compartido entre mensajes:
    # la escucha y el cooldown deben sobrevivir al ciclo on_message.
    spectator_effective = load_policy()
    shared_spectator_buffer = PassiveBuffer(
        buffer_max=spectator_effective.buffer_max,
        ttl_seconds=spectator_effective.ttl_seconds,
        clock=time.time,
    )
    shared_spectator_gate = ActivitiesCooldown(
        cooldown_seconds=spectator_effective.cooldown_seconds,
        clock=time.time,
    )
    shared_spectator_session = SpectatorSessionRegistry(
        clock=time.time,
        active_idle_seconds=spectator_effective.active_idle_seconds,
        proactive_idle_seconds=spectator_effective.proactive_idle_seconds,
    )
    shared_conversation_tasks = ConversationTaskRegistry(clock=time.monotonic)

    # Pegamentos Discord↔dominio (citas, regalos, diario). Ver `build_date_glue`.
    glue = build_date_glue(
        state,
        llm_base_url=LLM_BASE_URL,
        request_timeout=REQUEST_TIMEOUT,
    )

    def build_app_state():
        return state

    def build_conversation_service(session, state, channel):
        return ConversationService(
            llm=build_llm(session, timeout=REQUEST_TIMEOUT, base_url=LLM_BASE_URL),
            state=state,
            search=BraveSearchClient(BRAVE_API_KEY, session, max_results=MAX_WEB_RESULTS),
            gifs=NekosBestProvider(session, contact=NEKOSBEST_CONTACT, timeout=GIF_TIMEOUT),
            notifier=DiscordNotifier(channel),
            clock=time.time,
            date_delta_max=DATE_DELTA_MAX,
        )

    def build_storage_info():
        """Diagnóstico seguro: nunca incluye diario, memorias ni respuestas."""
        pending = sum(
            1
            for record in (state.turn_records or {}).values()
            if isinstance(record, dict) and record.get("status") == "committed"
        )
        return {
            "path": str(store.active_path),
            "schema_version": CURRENT_SCHEMA_VERSION,
            "state_version": int(state.state_version),
            "recovered": bool(boot.recovered),
            "migration": (
                boot.migration.status.value if boot.migration is not None else ""
            ),
            "pending_publications": pending,
            "quarantine_path": boot.load.quarantine_path,
        }

    def build_ctx(channel, pending_message_tracker=None):
        # Política efectiva del modo espectador, recalculada del entorno.
        # El buffer y el cooldown SON COMPARTIDOS entre mensajes (vida social
        # continua); solo la política se recalcula por mensaje.
        spectator_policy = load_policy()
        ctx = BotContext(
            channel_id=channel.id,
            state=build_app_state(),
            lock=commit_lock,
            owner_id=OWNER_ID,
            debounce_seconds=DEBOUNCE_SECONDS,
            request_timeout=REQUEST_TIMEOUT,
            llm_base_url=LLM_BASE_URL,
            llm_provider=LLM_CFG.provider,
            llm_health_check=LLM_CFG.health_check,
            trace_dir=settings.trace_dir,
            storage_info=build_storage_info(),
            persistence=boot.persistence,
            season_archiver=season_archiver,
            retention=retention,
            turn_journal=turn_journal,
            commit_lock=commit_lock,
            maybe_reflect=maybe_reflect,
            build_service=build_conversation_service,
            settle_relationship=settle_relationship,
            process_date_turn=glue.process_date_turn,
            add_diary_reflection=glue.add_diary_reflection,
            judge_gift=glue.judge_gift,
            evaluate_date_invitation=glue.evaluate_date_invitation,
            propose_scenes=glue.propose_scenes,
            busy_date_owner=glue.busy_date_owner,
            notify_busy=glue.notify_busy,
            date_busy_text=glue.date_busy_text,
            expire_stale_dates=glue.expire_stale_dates,
            resolve_question=glue.resolve_question,
            apply_question_result=glue.apply_question_result,
            expire_question=glue.expire_question,
            affinity_footer=lambda user: glue.affinity_footer_text(
                user.id, user.display_name
            ),
            log_diary_event=state.log_diary_event,
        )
        ctx.passive_buffer = shared_spectator_buffer
        ctx.pending_message_tracker = pending_message_tracker
        ctx.spectator_policy = spectator_policy
        ctx.spectator_gate = shared_spectator_gate
        ctx.spectator_session = shared_spectator_session
        ctx.conversation_task_context = shared_conversation_tasks
        ctx.timers = getattr(client, "_spectator_timers", None)
        ctx.dispatcher = getattr(client, "_spectator_dispatcher", None)
        ctx.handle_scene_choice = (
            lambda interaction, payload: discord_turn.handle_scene_choice(
                ctx, interaction, payload
            )
        )
        ctx.handle_date_action = (
            lambda interaction, payload: discord_turn.handle_date_action(
                ctx, interaction, payload
            )
        )
        ctx.handle_question_answer = (
            lambda interaction, payload: discord_turn.handle_question_answer(
                ctx, interaction, payload
            )
        )
        return ctx

    registry = build_registry()

    def apply_affinity_change(uid, delta, *, now=None, delta_max=None):
        return state.apply_affinity(uid, delta, now=now, delta_max=delta_max)

    def user_display_name(user_id):
        entry = users_data.get(str(user_id))
        if isinstance(entry, dict) and entry.get("name"):
            return str(entry["name"])
        return "alguien"

    async def settle_relationship(channel, now, session=None, user=None):
        """Compatibilidad: mantiene el bloqueo monógamo, sin coronar a nadie.

        La pareja oficial solo se confirma con una propuesta y una aceptación
        validadas por el dominio relacional. Esta función no crea parejas por
        puntuación de afinidad.
        """
        async with commit_lock:
            with persistence.transaction():
                if world_data.get("winner_id"):
                    apply_winner_lock(world_data, affinity_data)
                    state.save_affinity()
        return None

    async def on_ready_extra(discord_client):
        # Seed PRIMERO para no "matar" la última interacción humana.
        try:
            await seed_last_human_activity(
                discord_client,
                channel_id=CHANNEL_ID,
                session=shared_spectator_session,
                build_ctx=build_ctx,
                timers=getattr(discord_client, "_spectator_timers", None),
                dispatcher=getattr(discord_client, "_spectator_dispatcher", None),
            )
        except Exception:
            log.exception("Fallo al sembrar la actividad inicial; se continúa el arranque")
        await resume_pending(discord_client)

    async def resume_pending(discord_client):
        """Reanuda respuestas confirmadas que no llegaron a publicarse."""
        channel = discord_client.get_channel(CHANNEL_ID)
        if channel is None:
            try:
                channel = await discord_client.fetch_channel(CHANNEL_ID)
            except Exception:
                log.exception("No se pudo resolver el canal para reanudar envíos")
                return

        now = time.time()
        abandoned = turn_journal.abandon_stale_processing(
            now=now, ttl=settings.publish_ttl_seconds
        )
        if abandoned:
            log.warning(
                "Turnos interrumpidos marcados como fallidos: %d", abandoned
            )
        try:
            turn_journal.prune(
                now=now, retain_seconds=settings.turn_retention_seconds
            )
        except Exception:
            log.exception("No se pudo podar el registro de turnos")

        async def publish(record):
            text = record.reply_text or ""
            while text:
                await channel.send(text[:2000])
                text = text[2000:]

        resumer = PublicationResumer(
            turn_journal,
            ttl=settings.publish_ttl_seconds,
            clock=time.time,
        )
        published = await resumer.resume(publish)
        if published:
            log.info("Respuestas pendientes republicadas: %d", published)

    client = create_client(
        build_ctx=build_ctx,
        registry=registry,
        channel_id=CHANNEL_ID,
        on_ready_extra=on_ready_extra,
        manual_shutdown={
            "state": state,
            "persistence": persistence,
            "reason": manual_shutdown_reason,
        },
        pending_state=state,
    )

    def log_startup():
        log.info("Proveedor LLM: %s — %s", LLM_CFG.provider, LLM_BASE_URL)
        _time_zone, time_zone_label, time_zone_source = resolve_zone(settings.timezone)
        log.info(
            f"Zona horaria de {character_name()}: %s (origen: %s)",
            time_zone_label,
            time_zone_source,
        )
        if LLM_CFG.provider != "llama":
            if not LLM_CFG.api_key:
                log.warning(
                    "LLM_PROVIDER=%s sin LLM_API_KEY: la API podría rechazar las peticiones",
                    LLM_CFG.provider,
                )
            if LLM_CFG.model == DEFAULT_MODEL:
                log.warning(
                    "LLM_MODEL no configurado para proveedor remoto; se usa el modelo local predeterminado"
                )
        log.info("Búsqueda web: Brave Search API")
        log.info("Proveedor de GIFs: NekosBest API v2")
        log.info(
            "Afinidad máxima %d (elegibilidad, no confesión) · temporada %s",
            CONFESS_THRESHOLD,
            world_data.get("season"),
        )
        if world_data.get("winner_id"):
            log.info(f"{character_name()} ya tiene pareja: %s", world_data.get("winner_id"))
        if OWNER_ID:
            log.info("Dueño autorizado para reiniciar temporada: %s", OWNER_ID)
        if not NEKOSBEST_CONTACT:
            log.warning(
                "Define NEKOSBEST_CONTACT en .env con un correo o URL de contacto."
            )
        if not BRAVE_API_KEY:
            log.warning("Define BRAVE_API_KEY en .env para habilitar la búsqueda web.")

    log_startup()
    try:
        client.run(TOKEN)
    finally:
        run_lock.release()
