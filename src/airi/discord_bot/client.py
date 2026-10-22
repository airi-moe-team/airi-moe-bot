"""Cliente de Discord: solo enruta eventos hacia comandos y turnos.

`create_client` recibe un `build_ctx(channel) -> BotContext`, un
`CommandRegistry` y el id del canal autorizado. `on_message` se limita a:
autorizar → expirar citas → despachar comando → comprobar cita activa →
debounce → delegar el turno a `airi.discord_bot.turn`.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from contextlib import nullcontext
from types import SimpleNamespace

import discord

from airi.discord_bot import turn
from airi.domain.constants import DATE_DELTA_MAX
from airi.services.channel_queue import ChannelDispatcher

log = logging.getLogger(__name__)


class _Debouncer:
    """Une mensajes rápidos del MISMO (canal, autor)."""

    def __init__(self):
        self.pending = {}
        self.seq = {}

    def next_seq(self, key):
        value = self.seq.get(key, 0) + 1
        self.seq[key] = value
        return value

    def current_seq(self, key):
        return self.seq.get(key)

    def add(self, key, item):
        self.pending.setdefault(key, []).append(item)

    def pop(self, key):
        self.seq.pop(key, None)
        return self.pending.pop(key, [])

    def reset(self, channel_id, author_id):
        key = (channel_id, author_id)
        self.pending.pop(key, None)
        self.seq.pop(key, None)


def create_client(*, build_ctx, registry, channel_id, on_ready_extra=None):
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    debounce = _Debouncer()
    dispatcher = ChannelDispatcher()
    shutdown = {"started": False, "phase": "running"}

    def _wire_shutdown(ctx):
        """Conecta la decisión de Airi con el cierre global del cliente."""
        ctx.is_shutting_down = lambda: bool(shutdown["started"])

        async def request_shutdown(reason, user_id=None):
            if shutdown["started"]:
                log.info("Cierre ya en curso; se ignora la solicitud duplicada")
                return
            shutdown["started"] = True
            shutdown["phase"] = "closing"
            clean_reason = str(reason or "").strip()[:300]
            log.info("Airi decide desconectarse: %s", clean_reason)

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
                                "status": "closing",
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
                            entry = {"kind": "self", "reason": clean_reason}
                        entry["status"] = status
                        ctx.state.world["last_shutdown"] = entry
                        ctx.state.save_world()
                except Exception:
                    log.exception("No se pudo registrar el resultado del cierre")

            async def close_after_reply():
                # Deja terminar el envío de la despedida antes de cerrar.
                await asyncio.sleep(0.5)
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
                    log.error("El cierre no se confirmó; Airi sigue disponible")

            asyncio.create_task(close_after_reply())

        ctx.request_shutdown = request_shutdown

    def _reset_conversation(ctx, ch_id, author_id):
        debounce.reset(ch_id, author_id)
        ctx.state.histories.pop(ch_id, None)

    @client.event
    async def on_ready():
        log.info("Bot conectado como %s", client.user)
        log.info("Canal autorizado: %s", channel_id)
        if on_ready_extra is not None:
            try:
                await on_ready_extra(client)
            except Exception:
                log.exception("La tarea de arranque posterior falló")

    @client.event
    async def on_message(message):
        if shutdown["started"]:
            return
        if message.author.bot or message.channel.id != channel_id:
            return
        content = message.content.strip()
        if not content:
            return

        ctx = build_ctx(message.channel)
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
            await handler(ctx, message)
            return

        owner_id, _owner_session = ctx.busy_date_owner(exclude_id=message.author.id)
        if owner_id is not None:
            await ctx.notify_busy(message.channel, message.author)
            return

        key = (message.channel.id, message.author.id)
        seq = debounce.next_seq(key)
        debounce.add(key, (message.author, content))
        await asyncio.sleep(ctx.debounce_seconds)
        if debounce.current_seq(key) != seq:
            return
        merged = debounce.pop(key)
        if not merged:
            return
        await dispatcher.submit(
            message.channel.id,
            lambda: turn.run_user_turn(
                ctx, message.channel, message.author, merged, reply_target=message
            ),
            message_ids=[getattr(message, "id", None)],
        )

    return client


def build_date_glue(state, *, llm_url, request_timeout):
    """Pegamentos Discord↔dominio para citas, regalos y diario.

    Devuelve un `SimpleNamespace` con los callables que `BotContext` inyecta.
    Vive fuera de `run_bot` para poder testearlo sin levantar el bot (basta un
    `AppState` y, para las llamadas al modelo, un `session` doble).

    La migración hexagonal dejó estos métodos como stubs vacíos en `run_bot`,
    lo que rompía `!cita` (TypeError por firma) y `!regalo`.
    """
    from airi.adapters.discord_notifier import DiscordNotifier
    from airi.adapters.http_llm import HttpLlmClient
    from airi.domain.affinity import affinity_level, affinity_summary, clamp_delta
    from airi.domain.constants import (
        DATE_BUSY_NOTICE_COOLDOWN,
        DATE_QUESTION_DELTA_MAX,
        DATE_SCENE_MAX_TOKENS,
        DATE_SCENES,
        DIARY_REFLECTION_MIN_INTERVAL,
    )
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
        GIFT_JUDGE_PROMPT,
        GIFT_JUDGE_SCHEMA,
        SCENE_PROPOSAL_PROMPT,
        SCENE_PROPOSAL_SCHEMA,
        SYSTEM_PROMPT,
        affinity_prompt_section,
        preferences_prompt_section,
        relationship_status_section,
    )
    from airi.domain.text_filters import clean_reply
    from airi.services.date_service import DateService

    busy_notice_at = {}  # uid -> timestamp del último aviso (anti-spam).

    async def request_llama(session, messages, *, schema, max_tokens=None, temperature):
        llm = HttpLlmClient(
            llm_url,
            session,
            timeout=request_timeout,
        )
        text, _meta = await llm.chat_with_meta(
            messages,
            schema=schema,
            max_tokens=max_tokens,
            temperature=temperature,
            disable_thinking=True,
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
                temperature=0.9,
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
        recent = [str(g) for g in (recent_gifts or [])]
        recent_desc = ", ".join(recent) if recent else "(ninguno)"
        system_prompt = (
            SYSTEM_PROMPT
            + affinity_desc
            + relationship_desc
            + prefs_desc
            + GIFT_JUDGE_PROMPT
        )
        user_message = (
            f"{display} te acaba de regalar «{item}». "
            f"Regalos recientes que ya te ha hecho: {recent_desc}. "
            "Reacciona como Airi y decide, con tu criterio, si el regalo mueve tu "
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
                temperature=0.7,
            )
        except Exception:
            log.exception("No se pudo consultar a Airi sobre el regalo")
            return None
        parsed = extract_json_object(raw) if isinstance(raw, str) else None
        if not isinstance(parsed, dict):
            return None

        reply_raw = parsed.get("reply")
        reply = clean_reply(reply_raw) if isinstance(reply_raw, str) else ""
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
            "Airi juzga el regalo «%s»: delta %+d (motivo: %s)", item, delta, event
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
            f"🌸 **Airi está en una cita ahora mismo.** Está con **{name}**. "
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
    from io import BytesIO

    from dotenv import load_dotenv

    from airi.adapters.brave_search import BraveSearchClient
    from airi.adapters.discord_notifier import DiscordNotifier
    from airi.adapters.http_llm import HttpLlmClient
    from airi.adapters.instance_lock import (
        InstanceAlreadyRunningError,
        InstanceLock,
    )
    from airi.adapters.nekosbest import NekosBestProvider
    from airi.adapters.state_store import StateStore
    from airi.config import Settings
    from airi.discord_bot import embeds
    from airi.discord_bot import turn as discord_turn
    from airi.discord_bot.commands import build_registry
    from airi.discord_bot.context import BotContext
    from airi.domain.affinity import (
        AFFINITY_DELTA_MAX,
        AFFINITY_DELTA_MIN,
        apply_affinity_delta,
        apply_winner_lock,
        maybe_crown_winner,
    )
    from airi.domain.gifs import ALLOWED_GIF_TYPES, GIF_EMOTION_TITLES
    from airi.domain.state_schema import CURRENT_SCHEMA_VERSION
    from airi.domain.texts import confession_text
    from airi.logging_setup import install_correlation_format
    from airi.observability.trace_store import TraceStore
    from airi.services.bootstrap import BootstrapError, bootstrap_state
    from airi.services.conversation import ConversationService
    from airi.services.migration import LegacyMigrator
    from airi.services.publication import PublicationResumer
    from airi.services.retention import RetentionService
    from airi.services.season_archive import SeasonArchiver
    from airi.services.turn_journal import TurnJournal

    load_dotenv()

    log = logging.getLogger(__name__)

    # Configuración
    TOKEN = os.getenv("DISCORD_TOKEN")
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
    LLAMA_URL = os.getenv("LLAMA_URL", "http://127.0.0.1:8081").rstrip("/")
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

    # Datos globales
    commit_lock = asyncio.Lock()

    # Settings y almacén
    settings = Settings.from_env()
    trace_store = TraceStore(settings.trace_dir, settings.trace_keep_last)
    install_correlation_format()

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
    season_archiver = SeasonArchiver(settings.data_dir)
    retention = RetentionService(
        settings.data_dir,
        season_limit=settings.season_retention,
        backup_limit=settings.backup_retention,
    )

    # Pegamentos Discord↔dominio (citas, regalos, diario). Ver `build_date_glue`.
    glue = build_date_glue(
        state,
        llm_url=LLAMA_URL,
        request_timeout=REQUEST_TIMEOUT,
    )

    def build_app_state():
        return state

    def build_conversation_service(session, state, channel):
        return ConversationService(
            llm=HttpLlmClient(
                LLAMA_URL,
                session,
                timeout=REQUEST_TIMEOUT,
            ),
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

    def build_ctx(channel):
        ctx = BotContext(
            channel_id=channel.id,
            state=build_app_state(),
            lock=commit_lock,
            owner_id=OWNER_ID,
            debounce_seconds=DEBOUNCE_SECONDS,
            request_timeout=REQUEST_TIMEOUT,
            llama_url=LLAMA_URL,
            trace_dir=settings.trace_dir,
            storage_info=build_storage_info(),
            persistence=boot.persistence,
            season_archiver=season_archiver,
            retention=retention,
            turn_journal=turn_journal,
            commit_lock=commit_lock,
            build_service=build_conversation_service,
            settle_relationship=settle_relationship,
            process_date_turn=glue.process_date_turn,
            add_diary_reflection=glue.add_diary_reflection,
            judge_gift=glue.judge_gift,
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

    async def send_selected_gif(session, channel, user, gif_type):
        """Envía un GIF de NekosBest (usado para la confesión)."""
        if gif_type == "none" or gif_type not in ALLOWED_GIF_TYPES:
            return
        log.info("El modelo ha seleccionado el GIF: %s", gif_type)
        provider = NekosBestProvider(
            session, contact=NEKOSBEST_CONTACT, timeout=GIF_TIMEOUT
        )
        gif_bytes = await provider.fetch(gif_type)
        if not gif_bytes:
            log.warning("No se encontró un GIF válido en NekosBest para %s", gif_type)
            return
        try:
            filename = f"airi_{gif_type}.gif"
            embed = discord.Embed(
                title=GIF_EMOTION_TITLES.get(gif_type, "Airi"),
                color=embeds.GIF_EMBED_COLOR,
            )
            if user is not None:
                embed.set_footer(
                    text=glue.affinity_footer_text(user.id, user.display_name),
                    icon_url=user.display_avatar.url,
                )
            embed.set_image(url=f"attachment://{filename}")
            file = discord.File(BytesIO(gif_bytes), filename=filename)
            await channel.send(embed=embed, file=file)
            log.info("GIF enviado correctamente: %s", gif_type)
        except discord.HTTPException:
            log.exception("Discord no pudo enviar el GIF")

    def user_display_name(user_id):
        entry = users_data.get(str(user_id))
        if isinstance(entry, dict) and entry.get("name"):
            return str(entry["name"])
        return "alguien"

    async def settle_relationship(channel, now, session=None, user=None):
        """Corona al ganador (confesión automática) y bloquea al resto."""
        winner = maybe_crown_winner(world_data, affinity_data, now)
        async with commit_lock:
            with persistence.transaction():
                if winner:
                    apply_winner_lock(world_data, affinity_data)
                    state.save_world()
                    state.save_affinity()
                    state.log_diary_event(
                        "confession",
                        winner,
                        f"Me he dado cuenta de que quiero estar con "
                        f"{user_display_name(winner)}. ¡Hoy nos hemos hecho novios!",
                    )
                elif world_data.get("winner_id"):
                    apply_winner_lock(world_data, affinity_data)
                    state.save_affinity()
        if winner:
            await channel.send(confession_text(user_display_name(winner)))
            log.info("¡Ganador coronado! %s es ahora pareja de Airi", winner)
            if session is not None and user is not None and str(user.id) == str(winner):
                try:
                    await send_selected_gif(session, channel, user, "kiss")
                except Exception:
                    log.exception("No se pudo enviar el GIF de la confesión")
            return winner
        return None

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
        on_ready_extra=resume_pending,
    )

    def log_startup():
        log.info("API local: %s", LLAMA_URL)
        log.info("Búsqueda web: Brave Search API")
        log.info("Proveedor de GIFs: NekosBest API v2")
        log.info(
            "Simulador de citas activo: confesión al llegar a %d (temporada %s)",
            CONFESS_THRESHOLD,
            world_data.get("season"),
        )
        if world_data.get("winner_id"):
            log.info("Airi ya tiene pareja: %s", world_data.get("winner_id"))
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
