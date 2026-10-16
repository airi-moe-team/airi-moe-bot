"""Cliente de Discord: solo enruta eventos hacia comandos y turnos.

`create_client` recibe un `build_ctx(channel) -> BotContext`, un
`CommandRegistry` y el id del canal autorizado. `on_message` se limita a:
autorizar → expirar citas → despachar comando → comprobar cita activa →
debounce → delegar el turno a `airi.discord_bot.turn`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace

import discord

from airi.discord_bot import turn
from airi.domain.constants import DATE_DELTA_MAX
from airi.domain.texts import DATE_QUESTION_NUDGE_TEXT, DATE_SCENE_TIMEOUT_TEXT

log = logging.getLogger(__name__)

# Momento de arranque del proceso: sirve para avisar si el `.env` se editó
# DESPUÉS (las constantes DATE_*/LLM_* se leen al importar y no se recargan).
STARTED_AT = time.time()


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


def create_client(*, build_ctx, registry, channel_id):
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    debounce = _Debouncer()

    def _reset_conversation(ctx, ch_id, author_id):
        debounce.reset(ch_id, author_id)
        ctx.state.histories.pop(ch_id, None)

    @client.event
    async def on_ready():
        log.info("Bot conectado como %s", client.user)
        log.info("Canal autorizado: %s", channel_id)

    @client.event
    async def on_message(message):
        if message.author.bot or message.channel.id != channel_id:
            return
        content = message.content.strip()
        if not content:
            return

        ctx = build_ctx(message.channel)
        ctx.reset_conversation = (
            lambda ch_id, author_id: _reset_conversation(ctx, ch_id, author_id)
        )

        if ctx.expire_stale_dates():
            await message.channel.send(
                "🌙 «Vaya, se me ha ido el tiempo... la cita se queda aquí. "
                "*se despide con la mano, algo apenada*»"
            )
        ctx.expire_stale_questions()

        # Peticiones de escena caducadas (el jugador nunca escribió el plan).
        if str(message.author.id) in ctx.expire_scene_requests():
            await message.channel.send(DATE_SCENE_TIMEOUT_TEXT)

        handler = registry.match(content)
        if handler is not None:
            ctx.clear_scene_request(message.author.id)
            await handler(ctx, message)
            return

        if ctx.pending_scene(message.author.id):
            ctx.take_pending_scene(message.author.id)
            await turn.start_date_with_scene(
                ctx, message.channel, message.author, content
            )
            return

        session = ctx.state.dates.get(str(message.author.id))
        if (
            isinstance(session, dict)
            and session.get("state") == "active"
            and session.get("question_pending")
        ):
            await message.channel.send(DATE_QUESTION_NUDGE_TEXT)
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
        await turn.run_user_turn(
            ctx, message.channel, message.author, merged, reply_target=message
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
        DATE_QUESTION_TIMEOUT,
        DATE_SCENE_TIMEOUT,
        DIARY_REFLECTION_MIN_INTERVAL,
        LLM_OUTPUT_TOKENS,
    )
    from airi.domain.dates import date_expired, date_seconds_left
    from airi.domain.diary import add_diary_entry, new_diary_entry
    from airi.domain.llm_output import extract_json_object
    from airi.domain.prompts import (
        GIFT_JUDGE_PROMPT,
        GIFT_JUDGE_SCHEMA,
        SYSTEM_PROMPT,
        affinity_prompt_section,
        preferences_prompt_section,
        relationship_status_section,
    )
    from airi.domain.text_filters import clean_reply
    from airi.domain.texts import DATE_SCENE_REQUEST_TEXT
    from airi.services.date_service import DateService

    busy_notice_at = {}  # uid -> timestamp del último aviso (anti-spam).
    pending_scenes = {}  # uid -> timestamp de la petición de escena.
    # Motor de citas reutilizable: conserva el RNG entre llamadas (la pregunta
    # decisiva tira el dado aquí, no en el modelo).
    date_engine = DateService(state=state)

    async def request_llama(session, messages, *, schema, max_tokens=None, temperature):
        llm = HttpLlmClient(
            llm_url,
            session,
            timeout=request_timeout,
        )
        text, _meta = await llm.chat_with_meta(
            messages,
            schema=schema,
            max_tokens=max_tokens or LLM_OUTPUT_TOKENS,
            temperature=temperature,
            disable_thinking=True,
            strict_schema=True,
        )
        return text

    # --- Escena por texto libre -------------------------------------------

    def request_scene(user_id, now=None):
        """Marca que se espera la escena del jugador y devuelve el texto."""
        pending_scenes[str(user_id)] = time.time() if now is None else now
        return DATE_SCENE_REQUEST_TEXT

    def pending_scene(user_id, now=None):
        """True si hay una petición de escena viva (no caducada) para ese usuario."""
        uid = str(user_id)
        ts = pending_scenes.get(uid)
        if ts is None:
            return False
        now = time.time() if now is None else now
        if now - float(ts) > DATE_SCENE_TIMEOUT:
            pending_scenes.pop(uid, None)
            return False
        return True

    def take_pending_scene(user_id, now=None):
        """Consume la petición de escena (True si existía y no había caducado)."""
        uid = str(user_id)
        if not pending_scene(uid, now=now):
            return False
        pending_scenes.pop(uid, None)
        return True

    def clear_scene_request(user_id):
        pending_scenes.pop(str(user_id), None)

    def expire_scene_requests(now=None):
        """Descarta peticiones de escena caducadas. Devuelve la lista de uids."""
        now = time.time() if now is None else now
        expired = []
        for uid, ts in list(pending_scenes.items()):
            if now - float(ts) > DATE_SCENE_TIMEOUT:
                pending_scenes.pop(uid, None)
                expired.append(uid)
        return expired

    # --- Pregunta decisiva -------------------------------------------------

    def resolve_question(session, index):
        return date_engine.resolve_question(session, index)

    def apply_question_result(session, result, *, user_id, now=None):
        return date_engine.apply_question_result(
            session, result, user_id=user_id, now=now
        )

    def expire_question(user_id, notify_channel=None):
        """La pregunta caducó sin respuesta: la cita sigue sin mover afinidad.

        Con `notify_channel` se avisa en el canal (best-effort) de que el
        momento pasó; el mensaje es in-fiction y no bloquea el flujo.
        """
        session = state.dates.get(str(user_id))
        if not isinstance(session, dict) or not session.get("question_pending"):
            return
        session["question_pending"] = False
        state.save_dates()
        log.info("Pregunta de %s caducada sin respuesta", user_id)
        if notify_channel is not None:
            from airi.domain.texts import DATE_QUESTION_MISSED_TEXT

            return notify_channel.send(DATE_QUESTION_MISSED_TEXT)
        return None

    def expire_stale_questions(now=None):
        """Barrido de preguntas huérfanas (p. ej. tras un reinicio del bot).

        Si la vista con los botones se perdió, la pregunta quedaría pendiente
        para siempre y el nudge bloquearía al jugador. Devuelve los uids limpiados.
        """
        if now is None:
            now = time.time()
        expired = []
        for uid, session in list(state.dates.items()):
            if not isinstance(session, dict) or not session.get("question_pending"):
                continue
            asked = float(session.get("question_asked_at", 0.0) or 0.0)
            if asked and now - asked > DATE_QUESTION_TIMEOUT:
                session["question_pending"] = False
                expired.append(uid)
        if expired:
            state.save_dates()
            log.info("Preguntas caducadas: %s", ", ".join(expired))
        return expired

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
        http_session=None,
        *,
        text,
        delta,
        points,
        date_decision,
        date_reason,
        last_chance_result,
        now,
        question=None,
        allow_crisis_drop=True,
    ):
        """Avanza un turno de la cita y cierra si toca.

        Devuelve el evento del turno (ver airi.domain.dates.step_date). La
        lógica vive en `airi.services.date_service.DateService`. `http_session`
        (aiohttp.ClientSession) habilita el resumen de cierre en el diario.
        """
        llm_chat = None
        if http_session is not None:
            async def llm_chat(messages, *, max_tokens=None):
                return await request_llama(
                    http_session,
                    messages,
                    schema=None,
                    max_tokens=max_tokens,
                    temperature=0.4,
                )

        service = DateService(
            state=state,
            notifier=DiscordNotifier(channel),
            rng=date_engine.rng,
            llm_chat=llm_chat,
        )
        return await service.process_turn(
            date_session,
            user=user,
            text=text,
            delta=delta,
            points=points,
            date_decision=date_decision,
            date_reason=date_reason,
            last_chance_result=last_chance_result,
            now=now,
            question=question,
            allow_crisis_drop=allow_crisis_drop,
        )

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
                _finish_date(uid, session, "timeout", now=now)
        if expired:
            log.info(
                "Citas caducadas por tiempo: %s (evento=timeout)",
                ", ".join(expired),
            )
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
        request_scene=request_scene,
        pending_scene=pending_scene,
        take_pending_scene=take_pending_scene,
        clear_scene_request=clear_scene_request,
        expire_scene_requests=expire_scene_requests,
        resolve_question=resolve_question,
        apply_question_result=apply_question_result,
        expire_question=expire_question,
        expire_stale_questions=expire_stale_questions,
        judge_gift=judge_gift,
        process_date_turn=process_date_turn,
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
    from pathlib import Path

    from dotenv import load_dotenv

    from airi.adapters.brave_search import BraveSearchClient
    from airi.adapters.discord_notifier import DiscordNotifier
    from airi.adapters.http_llm import HttpLlmClient
    from airi.adapters.json_repo import load_json, load_json_list, save_json
    from airi.adapters.nekosbest import NekosBestProvider
    from airi.config import Settings
    from airi.discord_bot import embeds
    from airi.discord_bot import turn as discord_turn
    from airi.discord_bot.commands import build_registry
    from airi.discord_bot.context import BotContext
    from airi.domain.affinity import (
        apply_affinity_delta,
        apply_winner_lock,
        maybe_crown_winner,
    )
    from airi.domain.constants import AFFINITY_DELTA_MAX, AFFINITY_DELTA_MIN
    from airi.domain.gifs import ALLOWED_GIF_TYPES, GIF_EMOTION_TITLES
    from airi.domain.texts import confession_text
    from airi.logging_setup import install_correlation_format
    from airi.observability.trace_store import TraceStore
    from airi.services.conversation import ConversationService
    from airi.services.state import AppState

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
    generation_lock = asyncio.Lock()
    settings = Settings.from_env()
    world_data_dir = settings.data_dir
    world_file = os.path.join(world_data_dir, "world.json")
    affinity_file = os.path.join(world_data_dir, "affinity.json")
    dates_file = os.path.join(world_data_dir, "dates.json")
    diary_file = os.path.join(world_data_dir, "diary.json")
    memories_file = os.path.join(world_data_dir, "memories.json")
    users_file = os.path.join(world_data_dir, "users.json")

    # Lock de instancia única: dos bots sobre el mismo `data/` se pisarían los
    # JSON. `AIRI_ALLOW_MULTI_INSTANCE=1` permite continuar (con aviso).
    from airi.locking import InstanceLock

    lock = InstanceLock(Path(world_data_dir) / ".airi.lock")
    if not lock.acquire():
        if os.environ.get("AIRI_ALLOW_MULTI_INSTANCE") == "1":
            log.warning(
                "Otra instancia tiene el lock de %s; se continúa por petición.",
                lock.path,
            )
        else:
            log.error(
                "Ya hay una instancia de Airi corriendo (lock %s). Saliendo. "
                "Usa AIRI_ALLOW_MULTI_INSTANCE=1 para forzar.",
                lock.path,
            )
            raise SystemExit(1)

    # Aviso de configuración obsoleta: las constantes DATE_*/LLM_* se leen al
    # importar, así que un `.env` editado después no surte efecto hasta reiniciar.
    env_path = Path(".env")
    if env_path.exists() and env_path.stat().st_mtime > STARTED_AT:
        log.warning(
            "El .env es más reciente que el arranque del bot: las constantes "
            "DATE_*/LLM_* se leen al importar. Reinicia para aplicarlas."
        )

    # Cargar datos (cargas robustas: un JSON corrupto o ausente no revienta el
    # arranque; se parte del valor por defecto).
    world_data = load_json(world_file, {})
    affinity_data = load_json(affinity_file, {})
    dates_data = load_json(dates_file, {})
    diary_data = load_json_list(diary_file)
    memories_data = load_json(memories_file, {})
    users_data = load_json(users_file, {})

    # Persistencia (escrituras atómicas: tmp + os.replace).
    def save_world():
        save_json(world_file, world_data)

    def save_affinity():
        save_json(affinity_file, affinity_data)

    def save_dates():
        save_json(dates_file, dates_data)

    def save_diary():
        save_json(diary_file, diary_data)

    def save_memories():
        save_json(memories_file, memories_data)

    def save_users():
        save_json(users_file, users_data)

    # Observabilidad
    trace_store = TraceStore(settings.trace_dir, settings.trace_keep_last)
    install_correlation_format()

    # Estado
    state = AppState(
        world=world_data,
        affinity=affinity_data,
        dates=dates_data,
        diary=diary_data,
        memories=memories_data,
        users=users_data,
        save_world=save_world,
        save_affinity=save_affinity,
        save_dates=save_dates,
        save_diary=save_diary,
        save_memories=save_memories,
        save_users=save_users,
        apply_affinity_fn=(
            lambda uid, delta, now=None, delta_max=AFFINITY_DELTA_MAX,
            delta_min=AFFINITY_DELTA_MIN: (
                lambda entry: apply_affinity_delta(
                    entry, delta, now or time.time(), delta_max, delta_min
                )
            )(state.affinity_entry(uid))
        ),
        traces=trace_store,
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

    def build_ctx(channel):
        ctx = BotContext(
            channel_id=channel.id,
            state=build_app_state(),
            lock=generation_lock,
            owner_id=OWNER_ID,
            debounce_seconds=DEBOUNCE_SECONDS,
            request_timeout=REQUEST_TIMEOUT,
            llama_url=LLAMA_URL,
            trace_dir=settings.trace_dir,
            trace_keep_raw=True,
            build_service=build_conversation_service,
            settle_relationship=settle_relationship,
            process_date_turn=glue.process_date_turn,
            add_diary_reflection=glue.add_diary_reflection,
            judge_gift=glue.judge_gift,
            request_scene=glue.request_scene,
            pending_scene=glue.pending_scene,
            take_pending_scene=glue.take_pending_scene,
            clear_scene_request=glue.clear_scene_request,
            resolve_question=glue.resolve_question,
            apply_question_result=glue.apply_question_result,
            expire_question=glue.expire_question,
            expire_stale_questions=glue.expire_stale_questions,
            expire_scene_requests=glue.expire_scene_requests,
            busy_date_owner=glue.busy_date_owner,
            notify_busy=glue.notify_busy,
            date_busy_text=glue.date_busy_text,
            expire_stale_dates=glue.expire_stale_dates,
            affinity_footer=lambda user: glue.affinity_footer_text(
                user.id, user.display_name
            ),
            log_diary_event=state.log_diary_event,
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
        if winner:
            apply_winner_lock(world_data, affinity_data)
            save_world()
            save_affinity()
            await channel.send(confession_text(user_display_name(winner)))
            state.log_diary_event(
                "confession",
                winner,
                f"Me he dado cuenta de que quiero estar con "
                f"{user_display_name(winner)}. ¡Hoy nos hemos hecho novios!",
            )
            log.info("¡Ganador coronado! %s es ahora pareja de Airi", winner)
            if session is not None and user is not None and str(user.id) == str(winner):
                try:
                    await send_selected_gif(session, channel, user, "kiss")
                except Exception:
                    log.exception("No se pudo enviar el GIF de la confesión")
            return winner
        if world_data.get("winner_id"):
            apply_winner_lock(world_data, affinity_data)
            save_affinity()
        return None

    client = create_client(build_ctx=build_ctx, registry=registry, channel_id=CHANNEL_ID)

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
    client.run(TOKEN)
