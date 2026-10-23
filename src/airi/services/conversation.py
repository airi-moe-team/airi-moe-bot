"""Servicio de conversación: un turno completo sin Discord ni HTTP directo."""

from __future__ import annotations

import asyncio
import json
import re
import time
import traceback
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Callable

import aiohttp

from airi.domain import memories as domain_memories
from airi.domain import prompts as domain_prompts
from airi.domain import users as domain_users
from airi.domain.affinity import (
    AFFINITY_DELTA_MAX,
    affinity_level,
    entry_points,
    is_winner,
    level_rank,
)
from airi.domain.constants import (
    AFFINITY_VIEW_SCOPE,
    DATE_HISTORY_MAX,
    DIARY_REFLECTION_MIN_INTERVAL,
    LLM_SHORT_MAX_TOKENS,
    MAX_HISTORY_MESSAGES,
    QUICK_HISTORY_MESSAGES,
    QUICK_REPLY_MAX_CHARS,
    SEARCH_QUERY_MAX_TOKENS,
)
from airi.domain.diary import add_diary_entry, new_diary_entry
from airi.domain.gifs import ALLOWED_GIF_TYPES
from airi.domain.grounding import reply_seems_grounded
from airi.domain.history_tags import AffinityInfo, build_inference_history, normalize_name
from airi.domain.llm_output import (
    RESPONSE_SCHEMA,
    ModelOutput,
    assistant_history_content,
    parse_model_output,
)
from airi.domain.narrative_claims import disconnect_claim_problem
from airi.domain.prompts import SEARCH_QUERY_PROMPT
from airi.domain.relationship_claims import (
    relationship_claim_problem,
    soften_relationship_claims,
)
from airi.domain.relationships import RelationshipFingerprint
from airi.domain.self_model import (
    apply_self_update,
    sync_preferences_from_self,
)
from airi.domain.text_filters import clean_reply, strip_repetition_loop
from airi.domain.turn_guard import DateFingerprint, fingerprint_of
from airi.domain.web import needs_web_search
from airi.logging_setup import (
    get_logger,
    reset_correlation_id,
    set_correlation_id,
)
from airi.observability.trace import TurnEvent
from airi.observability.trace_store import TraceStore
from airi.ports.llm import LLMMeta
from airi.services.relationships import RelationshipService
from airi.services.state import AppState

log = get_logger(__name__)

# Contexto que recibe el modelo cuando la búsqueda web no da resultados.
SEARCH_FAILED_CONTEXT = (
    "La búsqueda web falló o no devolvió resultados. "
    "No afirmes que buscaste con éxito ni inventes datos "
    "actuales. Comunica esta limitación con naturalidad."
)

# Respuesta honesta cuando el grounded-check detecta datos inventados.
GROUNDED_FALLBACK_TEXT = (
    "Mmm... he mirado en la web, pero no he encontrado una "
    "información fiable sobre eso. Prefiero no inventarme datos. "
    "¿Quieres que busque con otras palabras, o me das más pistas "
    "sobre qué fuente prefieres consultar?"
)

# Palabras que piden contexto o efectos que el turno rápido no cubre: si
# aparecen, se usa el prompt completo aunque el mensaje sea corto.
_QUICK_BLOCKED_HINTS = (
    "recuerda",
    "acuerdas",
    "memoria",
    "diario",
    "cita",
    "pareja",
    "novi",
    "amor",
    "quieres",
    "sientes",
    "regalo",
    "ayer",
    "antes",
    "pasado",
    "olvida",
    "promesa",
    "secreto",
    "relación",
    "relacion",
)

# Errores HTTP que sí justifican reintentar sin salida estricta (servidor que
# no soporta json_schema). Un timeout o un fallo de conexión NO se reintenta:
# repetir la espera duplicaría la latencia sin cambiar el resultado.
_STRICT_RETRY_STATUSES = (400, 404, 405, 415, 422, 501)

#: Niveles de afinidad negativos: el GIF de respaldo refleja ese malestar.
_NEGATIVE_AFFINITY_LEVELS = ("Distante", "Molesta", "Enfadada", "Bloqueada")


def guaranteed_gif(gif_type, level_name):
    """Devuelve siempre una emoción válida; `none` se sustituye por una afín.

    El modelo debería elegir siempre una, pero el contrato admite `none` por
    compatibilidad. Aquí se garantiza que cada turno lleve GIF y que el respaldo
    no contradiga el tono: feliz por defecto, negativo si la afinidad es hostil.
    """
    if (
        isinstance(gif_type, str)
        and gif_type in ALLOWED_GIF_TYPES
        and gif_type != "none"
    ):
        return gif_type
    return "nope" if level_name in _NEGATIVE_AFFINITY_LEVELS else "happy"


MEMORY_SAVED_NOTICE = "Airi recordará este evento"
SELF_CHANGED_NOTICE = (
    "Airi acaba de cambiar algo de sí misma — escribe `!identidad-airi` "
    "para ver quién es ahora"
)

DISCONNECT_REPAIR_PROMPT = (
    "Tu respuesta anterior no fue coherente con tu decisión de marcharte. "
    "Devuelve de nuevo el objeto JSON completo: si en \"reply\" dices que te "
    "vas, que te duermes o que te desconectas, \"disconnect.leave\" debe ser "
    "true con un motivo breve; si te quedas, \"leave\" debe ser false y no "
    "debes despedirte como si te fueras. No añadas texto fuera del JSON."
)

QUESTION_CLOSE_REPAIR_PROMPT = (
    "Estás encadenando cierres con pregunta en una charla casual y suena a "
    "asistente, no a persona. Devuelve de nuevo el objeto JSON completo (mismo "
    "esquema, mismas reglas) reescribiendo SOLO el cierre de \"reply\": "
    "elimina la pregunta del final —también las retóricas tipo \"¿no?\", "
    "\"¿verdad?\"— y termina con una afirmación, tu opinión o una broma que "
    "de a la otra persona la opción de responder o no. Si ya había una "
    "pregunta a mitad del mensaje que aporte algo concreto, tampoco la "
    "acumules: responde sin interrogar salvo que te falte un dato esencial "
    "para continuar. No escribas texto fuera del JSON."
)

EMPTY_REPLY_REPAIR_PROMPT = (
    "La respuesta llegó vacía o sin \"reply\" legible. Devuelve de nuevo el "
    "objeto JSON completo con un \"reply\" breve, natural y NUEVO que reaccione "
    "al último mensaje de la conversación; no sirve responder con \"none\", con "
    "asteriscos solos ni con cadenas vacías. No escribas texto fuera del JSON."
)

REPEAT_REPAIR_PROMPT = (
    "La respuesta repite casi literal un turno anterior del historial y eso "
    "está prohibido. Devuelve de nuevo el objeto JSON completo con una "
    "respuesta NUEVA: otra apertura, otro enfoque y otro cierre; reacciona a lo "
    "que la persona dijo AHORA, no a los turnos viejos. Está prohibido "
    "reutilizar frases tal cual de respuestas anteriores. No escribas texto "
    "fuera del JSON."
)

#: Longitud mínima (normalizada) para considerar copia literal de un turno.
REPEAT_PREFIX_MIN = 40


def _normalized_reply(text) -> str:
    """Normaliza una respuesta para compararla contra turnos previos."""
    t = (text or "").lower()
    # Las acciones narrativas y la puntuación no cuentan para el parecido.
    t = re.sub(r"\*[^*]*\*", " ", t)
    t = re.sub(r"[^\w\s¿?¡!~]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def reply_repeats_history(
    text, history, *, min_prefix: int = REPEAT_PREFIX_MIN
) -> bool:
    """True si `text` copia el arranque de alguna respuesta anterior de Airi.

    Comparación por prefijo normalizado: detecta el patrón observado en
    producción (abrir con el mismo enunciado que un turno viejo y variar solo
    el final). Respuestas muy cortas no se marcan: los saludos pequeños se
    solapan por naturaleza.
    """
    norm = _normalized_reply(text)
    if len(norm) < min_prefix:
        return False
    for msg in history or []:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        prev = content
        if isinstance(content, str) and content.lstrip().startswith("{"):
            try:
                data = json.loads(content)
            except ValueError:
                data = None
            if isinstance(data, dict):
                prev = data.get("reply")
        prev_norm = _normalized_reply(prev if isinstance(prev, str) else "")
        if len(prev_norm) < min_prefix:
            continue
        if (
            norm.startswith(prev_norm[:min_prefix])
            or prev_norm.startswith(norm[:min_prefix])
        ):
            return True
    return False


def strip_trailing_question(text: str) -> str:
    """Recorta la oración interrogativa final.

    Red de seguridad determinista contra el patrón «preguntón» (charla casual
    que encadena cierres con pregunta): si tras la regeneración la respuesta
    sigue terminando en `?`, se elimina esa oración final —span desde el último
    `¿` de apertura— y el resto se devuelve limpio. Si la pregunta no lleva `¿`
    o `¿` está al inicio, cae al recorte por delimitadores de oración
    (., !, ¡, ~, * y salto de línea). Nunca devuelve vacío: si no queda texto
    fuera de la pregunta, se devuelve la respuesta tal cual.
    """
    cleaned = (text or "").rstrip()
    if not cleaned or not cleaned.endswith("?"):
        return text

    # 1) Delimitador natural: el último '¿' que abre la oración final.
    open_idx = cleaned.rfind("¿")
    if open_idx > 0:
        remainder = cleaned[:open_idx].rstrip()
        return remainder if remainder.strip() else text

    # 2) Fallback sin '¿': última oración por delimitadores de cierre.
    sentence_start = max(
        cleaned.rfind(ch, 0, -1) for ch in (".", "!", "¡", "\n", "*", "~")
    )
    if sentence_start < 0:
        return text
    remainder = cleaned[:sentence_start + 1].rstrip()
    return remainder if remainder.strip() else text


def _read_only_memories(memories, user_id) -> list:
    """Vista de memorias que no crea una entrada vacía durante la generación."""
    entries = memories.get(str(user_id)) if isinstance(memories, dict) else None
    return list(entries) if isinstance(entries, list) else []


@dataclass
class TurnContext:
    channel_id: int | str = 0
    allow_web: bool = True
    now: float | None = None  # None → reloj del servicio (testeable)
    correlation_id: str | None = None  # None → se genera uno por turno
    kind: str = "message"  # message | gift | date_action | scene_select | command
    raw_input: str | None = None  # None → se une de `messages`
    on_trace: Callable[[TurnEvent], None] | None = None  # hook post-turno
    extra_note: str | None = None  # nota interna para el modelo (un solo turno)
    suppress_affinity: bool = False  # el turno NO mueve la afinidad
    # Clave estable reclamada por el diario de turnos (referencia de evidencia).
    turn_key: str | None = None


@dataclass
class TurnResult:
    reply: str | None = None
    gif: str = "none"
    gif_bytes: bytes | None = None
    memory_action: str = "none"
    diary_action: str = "none"
    affinity_delta: int = 0
    affinity_applied: int = 0
    affinity_event: str = "none"
    level_before: str = "Desconocida"
    level_after: str = "Desconocida"
    leveled_up: bool = False
    in_date: bool = False
    date_decision: str = "continue"
    date_reason: str = "none"
    last_chance_result: str = "none"
    date_question: object = None
    grounded: bool = True
    web_context: str | None = None
    memory_saved: bool = False
    diary_saved: bool = False
    self_changed: bool = False
    self_update_action: object = None
    # Relación afectiva
    romantic_stage_before: str = "none"
    romantic_stage_after: str = "none"
    romantic_update_action: object = None
    relationship_action_applied: str = "none"
    partner_confirmed: bool = False
    proposal_pending: bool = False
    relationship_claims_repaired: bool = False
    disconnect_reason: str | None = None
    history: list = field(default_factory=list)
    notices: list = field(default_factory=list)
    skipped: bool = False
    trace: TurnEvent | None = None


@dataclass
class TurnDraft:
    """Resultado de la generación, sin mutaciones de dominio."""

    user: object
    messages: tuple
    context: TurnContext
    history: list
    date_fingerprint: DateFingerprint | None
    season: int
    now: float
    output: ModelOutput
    answer: str
    gif_bytes: bytes | None
    web_context: str | None
    grounded: bool
    timings: dict
    trace: TurnEvent
    relationship_fingerprint: RelationshipFingerprint | None = None
    skipped: bool = False


class ConversationService:
    """Orquesta un turno: historial → búsqueda → LLM → filtros → afinidad."""

    def __init__(
        self,
        *,
        llm,
        state: AppState,
        search=None,
        gifs=None,
        notifier=None,
        clock=time.time,
        max_history: int = MAX_HISTORY_MESSAGES,
        date_delta_max: int = AFFINITY_DELTA_MAX,
        traces: TraceStore | None = None,
        affinity_scope: str | None = None,
    ):
        self.llm = llm
        self.state = state
        self.search = search
        self.gifs = gifs
        self.notifier = notifier
        self.clock = clock
        self.max_history = max_history
        self.date_delta_max = date_delta_max
        # Ámbito de la afinidad visible en el prompt: por defecto, solo la del
        # destinatario del turno (el resto de interlocutores, desconocidos).
        self.affinity_scope = affinity_scope or AFFINITY_VIEW_SCOPE
        # Almacén de eventos: por defecto el del AppState.
        self.traces = traces if traces is not None else getattr(state, "traces", None)
        # Estado romántico por usuario (etapas, evidencia y propuestas).
        self.relationships = RelationshipService(state)

    async def generate_turn(self, user, messages, ctx: TurnContext) -> TurnDraft:
        """Genera una respuesta sin mutar el estado de dominio."""
        import time as _time

        cid = ctx.correlation_id or uuid.uuid4().hex[:12]
        token = set_correlation_id(cid)
        merged_text = "\n".join(part for _, part in messages)
        ev = TurnEvent(
            kind=ctx.kind,
            correlation_id=cid,
            user_id=str(user.id),
            user_name=getattr(user, "display_name", str(user.id)),
            channel_id=str(ctx.channel_id),
            allow_web=ctx.allow_web,
            raw_input=ctx.raw_input if ctx.raw_input is not None else merged_text,
            messages_in=[
                {"author": getattr(w, "display_name", "?"), "text": p}
                for w, p in messages
            ],
        )
        now = ctx.now if ctx.now is not None else self.clock()
        uid = user.id
        timings = {}

        # Referencia estable del turno (la aporta TurnCoordinator; en llamadas
        # directas se sintetiza una local) y vista aislada de la relación.
        if not ctx.turn_key:
            ctx.turn_key = f"local:{ctx.channel_id}:{uid}:{int(now)}"
        relationship_view = self.relationships.view(
            uid, turn_key=ctx.turn_key, channel_id=ctx.channel_id, now=now
        )
        relationship_fingerprint = self.relationships.fingerprint(uid)

        try:
            log.info("turno user=%s", uid)

            # Snapshots ANTES de cualquier mutación (replay fiel).
            ev.state_snapshot_affinity = dict(self.state.affinity.get(str(uid), {}))
            ev.state_snapshot_world = dict(self.state.world)
            ev.state_snapshot_memories = list(self.state.memories.get(str(uid), []))
            ev.state_snapshot_diary = list(self.state.diary[-20:])
            _sess0 = self.state.dates.get(str(uid))
            ev.state_snapshot_date = dict(_sess0) if isinstance(_sess0, dict) else None
            ev.in_date = isinstance(_sess0, dict)
            ev.date_state = _sess0.get("state") if isinstance(_sess0, dict) else None
            ev.date_turns_before = (
                int(_sess0.get("turns", 0) or 0) if isinstance(_sess0, dict) else 0
            )
            ev.affinity_before = entry_points(self.state.affinity.get(str(uid)))

            # Durante una cita el historial es privado de esa cita; fuera de
            # ella se usa el historial público del canal.
            date_session = self.state.dates.get(str(uid))
            in_date = isinstance(date_session, dict)
            if in_date:
                history = list(date_session.get("history") or [])
            else:
                history = list(self.state.histories.get(ctx.channel_id, []))
            for who, part in messages:
                history.append({
                    "role": "user",
                    "content": part,
                    "author_id": str(who.id),
                    "author_name": getattr(who, "display_name", None),
                })
            ev.history_in = list(history)

            log.info("turno user=%s in_date=%s", uid, in_date)

            web_context = None
            search_query = None
            if ctx.allow_web and needs_web_search(merged_text):
                if self.notifier is not None:
                    await self.notifier.send(
                        "Un momentito, estoy buscando información en la web..."
                    )
                t0 = _time.perf_counter()
                search_query = await self._build_search_query(merged_text)
                log.info(
                    "Consulta original: %r -> reformulada: %r",
                    merged_text, search_query,
                )
                if self.search is not None:
                    web_context = await self.search.search(search_query)
                if web_context is None:
                    log.warning("La búsqueda web no devolvió resultados")
                    web_context = SEARCH_FAILED_CONTEXT
                timings["search_ms"] = int((_time.perf_counter() - t0) * 1000)
            ev.search_query = search_query
            ev.web_context = web_context

            delta_max = self.date_delta_max if in_date else AFFINITY_DELTA_MAX
            quick = self._is_quick_turn(
                merged_text,
                in_date=in_date,
                web_context=web_context,
                kind=ctx.kind,
                extra_note=ctx.extra_note,
                history=history,
                user=uid,
                display_name=getattr(user, "display_name", None),
            )
            t0 = _time.perf_counter()
            system_prompt, raw_llm, meta, output = await self._generate(
                history, web_context, user, date_session, delta_max,
                extra_note=ctx.extra_note,
                relationship_view=relationship_view,
                now=now,
                quick=quick,
            )
            timings["llm_ms"] = int((_time.perf_counter() - t0) * 1000)
            ev.prompt_system = system_prompt
            ev.raw_llm = raw_llm
            ev.llm_latency_ms = timings["llm_ms"]
            ev.llm_ms = timings["llm_ms"]
            ev.llm_finish_reason = meta.finish_reason
            ev.llm_usage = meta.usage
            ev.parse_ok = output.reply is not None
            ev.parsed = {
                "reply": output.reply,
                "gif": output.gif,
                "memory": output.memory,
                "diary": output.diary,
                "affinity_delta": output.affinity_delta,
                "affinity_event": output.affinity_event,
                "date_decision": output.date_decision,
                "date_reason": output.date_reason,
                "last_chance_result": output.last_chance_result,
                "date_question": output.date_question,
                "self_update": output.self_update,
                "romantic_update": output.romantic_update,
                "relationship_action": output.relationship_action,
            }
            # Sin filtro de duplicados: si el modelo repite, se publica igual.
            # Solo se cortan bucles internos de palabras dentro de la respuesta.
            answer = strip_repetition_loop(output.reply)
            if not answer:
                log.info("Se omitió una respuesta duplicada sin contenido nuevo.")
                ev.skipped = True
                ev.timings_ms = timings
                ev.finish()
                return TurnDraft(
                    user=user,
                    messages=tuple(messages),
                    context=ctx,
                    history=history,
                    date_fingerprint=fingerprint_of(date_session),
                    season=int(self.state.world.get("season", 1) or 1),
                    now=now,
                    output=output,
                    answer="",
                    gif_bytes=None,
                    web_context=web_context,
                    grounded=True,
                    timings=timings,
                    trace=ev,
                    relationship_fingerprint=relationship_fingerprint,
                    skipped=True,
                )

            # Filtro anti-alucinación antes de publicar.
            grounded = True
            if web_context and not reply_seems_grounded(answer, web_context):
                log.warning(
                    "La respuesta contenía datos no presentes en las fuentes; "
                    "se reemplaza por un mensaje honesto."
                )
                answer = GROUNDED_FALLBACK_TEXT
                output = ModelOutput(
                    answer, "none", "none", "none", 0, "continue", "none", "none",
                )
                grounded = False
            ev.grounded = grounded
            ev.final_reply = answer
            # Cada turno lleva GIF: si el modelo devolvió "none" (o un tipo
            # inválido), se sustituye por una emoción coherente con la afinidad.
            level_name = affinity_level(self.state.entry_points(uid))[0]
            gif_type = guaranteed_gif(output.gif, level_name)
            output = output._replace(gif=gif_type)
            ev.gif = gif_type
            ev.web_context = web_context

            gif_bytes = None
            if self.gifs is not None:
                gif_bytes = await self.gifs.fetch(gif_type)
            ev.gif_sent = gif_bytes is not None
            ev.gif_fetched = gif_bytes is not None
            ev.affinity_delta_requested = output.affinity_delta
            ev.timings_ms = timings
            ev.finish()

            return TurnDraft(
                user=user,
                messages=tuple(messages),
                context=ctx,
                history=history,
                date_fingerprint=fingerprint_of(date_session),
                season=int(self.state.world.get("season", 1) or 1),
                now=now,
                output=output,
                answer=answer,
                gif_bytes=gif_bytes,
                web_context=web_context,
                grounded=grounded,
                timings=timings,
                trace=ev,
                relationship_fingerprint=relationship_fingerprint,
            )
        except Exception as exc:
            ev.errors.append({
                "type": type(exc).__name__,
                "msg": str(exc),
                "tb": traceback.format_exc(),
            })
            ev.error = str(exc)
            ev.finish()
            await self._save_trace(ev)
            self._emit_trace(ctx, ev)
            raise
        finally:
            reset_correlation_id(token)

    def apply_turn(self, draft: TurnDraft) -> TurnResult:
        """Aplica las mutaciones de un borrador ya validado (síncrono)."""
        ev = draft.trace
        if draft.skipped:
            # El registro del interlocutor sí ocurre aunque la respuesta se
            # omita por ser duplicada.
            for who, _part in draft.messages:
                self._register_user(who, draft.now)
            return TurnResult(
                skipped=True,
                in_date=draft.date_fingerprint is not None,
                web_context=draft.web_context,
                history=list(draft.history),
                trace=ev,
            )

        for who, _part in draft.messages:
            self._register_user(who, draft.now)

        uid = draft.user.id
        date_session = self.state.dates.get(str(uid))
        in_date = draft.date_fingerprint is not None and isinstance(date_session, dict)
        entry = self.state.affinity_entry(uid)
        level_before = affinity_level(entry_points(entry))[0]
        output = draft.output
        answer = draft.answer
        disconnect_reason = (
            output.disconnect.get("reason") if output.disconnect else None
        )

        delta_to_apply = output.affinity_delta
        if draft.context.suppress_affinity:
            if delta_to_apply:
                log.info("El turno no mueve la afinidad (ya aplicada por el sistema).")
            delta_to_apply = 0
        delta_max = self.date_delta_max if in_date else AFFINITY_DELTA_MAX
        applied = self.state.apply_affinity(
            uid, delta_to_apply, now=draft.now, delta_max=delta_max
        )
        points_now = self.state.entry_points(uid)
        level_after = affinity_level(points_now)[0]
        leveled_up = level_rank(level_after) > level_rank(level_before)
        if leveled_up:
            self.state.log_diary_event(
                "level",
                draft.user,
                f"Empiezo a sentir algo más por {self.state.display_name(uid)}; "
                f"nuestra relación ha subido a «{level_after}».",
            )
        log.info(
            "afinidad %+d (aplicado %+d) total=%d (%s→%s)",
            output.affinity_delta, applied, points_now, level_before, level_after,
        )

        diary_saved = False
        if leveled_up and output.diary.lower() != "none":
            diary_saved = self._add_diary_reflection(uid, output.diary, draft.now)

        memory_saved = domain_memories.process_memory_action(
            self.state.memories, uid, output.memory, now=draft.now
        )
        notices = []
        if memory_saved:
            self.state.save_memories()
            notices.append(MEMORY_SAVED_NOTICE)

        # Deriva lenta: si han pasado los días configurados, los rasgos se
        # acercan un paso a su base. Es idempotente y no toca el núcleo.
        self.state.decay_self(now=draft.now)

        self_changed = False
        self_entry = None
        if output.self_update:
            source = "gift" if draft.context.kind == "gift" else (
                "date" if in_date else "message"
            )
            self_entry = apply_self_update(
                self.state.self_model(),
                output.self_update,
                now=draft.now,
                user_id=uid,
                source=source,
            )
            if self_entry:
                self_changed = True
                sync_preferences_from_self(self.state.world)
                self.state.save_identity()
                notices.append(SELF_CHANGED_NOTICE)

        # Relación afectiva: el modelo propone y el dominio decide dentro del
        # mismo commit que la afinidad y el resto de efectos del turno.
        relationship_outcome = self.relationships.apply(
            uid,
            update=output.romantic_update,
            action=output.relationship_action,
            turn_key=draft.context.turn_key,
            channel_id=draft.context.channel_id,
            now=draft.now,
            season=draft.season,
            display_name=getattr(draft.user, "display_name", None) or "",
            current_turn_text="\n".join(part for _, part in draft.messages),
        )
        partner_confirmed = relationship_outcome.partner_confirmed or is_winner(
            self.state.world, uid
        )
        claim_problem = relationship_claim_problem(
            answer,
            stage=relationship_outcome.stage_after,
            partner_confirmed=partner_confirmed,
            proposal_pending=relationship_outcome.pending_proposal is not None,
        )
        claims_repaired = False
        if claim_problem:
            log.warning("Afirmación relacional no confirmada: %s", claim_problem)
            repaired = soften_relationship_claims(
                answer,
                stage=relationship_outcome.stage_after,
                partner_confirmed=partner_confirmed,
            )
            claims_repaired = repaired != answer
            answer = repaired
        if relationship_outcome.partner_confirmed:
            notices.append(
                f"💗 **Airi y {self.state.display_name(uid)} ahora son pareja.**"
            )

        history = list(draft.history)
        history.append({
            "role": "assistant",
            "content": assistant_history_content(answer, output),
            "reply_to_user_id": str(uid),
            "reply_to_user_name": getattr(draft.user, "display_name", None),
        })
        if in_date and isinstance(date_session, dict):
            date_session["history"] = history[-DATE_HISTORY_MAX:]
            self.state.save_dates()
        else:
            self.state.histories[draft.context.channel_id] = history[-self.max_history:]
            self.state.save_state()

        ev.affinity_after = points_now
        ev.affinity_applied = applied
        ev.affinity_event = output.affinity_event
        ev.level_before = level_before
        ev.level_after = level_after
        ev.leveled_up = leveled_up
        ev.memory_saved = output.memory if memory_saved else None
        ev.diary_saved = output.diary if diary_saved else None
        ev.date_decision = output.date_decision
        ev.date_reason = output.date_reason
        ev.date_turns_after = (
            int(date_session.get("turns", 0) or 0)
            if in_date and isinstance(date_session, dict) else 0
        )
        ev.romantic_stage_before = relationship_outcome.stage_before
        ev.romantic_stage_after = relationship_outcome.stage_after
        ev.romantic_update = (
            relationship_outcome.update_entry.get("to")
            if relationship_outcome.update_entry else None
        )
        ev.relationship_action = relationship_outcome.action_applied
        ev.partner_confirmed = relationship_outcome.partner_confirmed
        ev.proposal_pending = relationship_outcome.pending_proposal is not None
        ev.relationship_claims_repaired = claims_repaired
        ev.relationship_notes = list(relationship_outcome.errors)
        ev.timings_ms = draft.timings

        return TurnResult(
            reply=answer,
            gif=output.gif,
            gif_bytes=draft.gif_bytes,
            memory_action=output.memory,
            diary_action=output.diary,
            affinity_delta=output.affinity_delta,
            affinity_applied=applied,
            affinity_event=output.affinity_event,
            level_before=level_before,
            level_after=level_after,
            leveled_up=leveled_up,
            in_date=in_date,
            date_decision=output.date_decision,
            date_reason=output.date_reason,
            last_chance_result=output.last_chance_result,
            date_question=output.date_question if in_date else None,
            grounded=draft.grounded,
            web_context=draft.web_context,
            memory_saved=memory_saved,
            diary_saved=diary_saved,
            self_changed=self_changed,
            self_update_action=self_entry,
            romantic_stage_before=relationship_outcome.stage_before,
            romantic_stage_after=relationship_outcome.stage_after,
            romantic_update_action=relationship_outcome.update_entry,
            relationship_action_applied=relationship_outcome.action_applied,
            partner_confirmed=relationship_outcome.partner_confirmed,
            proposal_pending=relationship_outcome.pending_proposal is not None,
            relationship_claims_repaired=claims_repaired,
            disconnect_reason=disconnect_reason,
            history=history,
            notices=notices,
            trace=ev,
        )

    async def run_turn(self, user, messages, ctx: TurnContext) -> TurnResult:
        """Compatibilidad: generar, aplicar y publicar avisos post-commit."""
        draft = await self.generate_turn(user, messages, ctx)
        try:
            result = self.apply_turn(draft)
        except Exception:
            await self._save_trace(draft.trace)
            self._emit_trace(ctx, draft.trace)
            raise
        await self.finish_trace(ctx, result.trace)
        for notice in result.notices:
            if self.notifier is not None:
                try:
                    await self.notifier.send(notice)
                except Exception:
                    log.warning("No se pudo enviar el aviso post-turno")
        return result

    async def _save_trace(self, trace: TurnEvent) -> None:
        if self.traces is not None:
            await self.traces.save(trace)

    async def finish_trace(self, ctx: TurnContext, trace: TurnEvent) -> None:
        await self._save_trace(trace)
        self._emit_trace(ctx, trace)

    # ------------------------------------------------------------------

    def _is_quick_turn(
        self,
        text,
        *,
        in_date,
        web_context,
        kind,
        extra_note,
        history=None,
        user=None,
        display_name=None,
    ):
        """True si el turno admite el contrato reducido y menos historial."""
        if in_date or web_context is not None or kind != "message" or extra_note:
            return False
        clean = " ".join((text or "").split())
        if not clean or len(clean) > QUICK_REPLY_MAX_CHARS:
            return False
        low = clean.casefold()
        if any(hint in low for hint in _QUICK_BLOCKED_HINTS):
            return False
        return not self._recent_context_is_mixed(history, user, display_name)

    @staticmethod
    def _recent_context_is_mixed(history, user, display_name):
        """True si la ventana reciente de grupo hace insuficiente el turno rápido.

        En un canal con varios interlocutores o respuestas de Airi dirigidas a
        otra persona conviene el prompt completo: el camino rápido recorta el
        historial justo cuando más hace falta distinguir a quién va dirigido
        cada sentimiento.
        """
        recent = (history or [])[-QUICK_HISTORY_MESSAGES:]
        if not recent:
            return False
        str_uid = str(user) if user is not None else None
        current_name = normalize_name(display_name) if display_name else ""
        other_authors = set()
        mixed_reply_to = False
        for msg in recent:
            if not isinstance(msg, Mapping):
                continue
            role = msg.get("role")
            if role == "user":
                author_id = msg.get("author_id")
                if author_id is not None:
                    str_author = str(author_id)
                    if str_uid is not None and str_author != str_uid:
                        other_authors.add(str_author)
                elif current_name:
                    name = normalize_name(msg.get("author_name"))
                    if name and name != current_name:
                        other_authors.add(name)
            else:
                reply_name = msg.get("reply_to_user_name")
                name = normalize_name(reply_name) if isinstance(reply_name, str) else ""
                if name and (not current_name or name != current_name):
                    mixed_reply_to = True
        return bool(other_authors or mixed_reply_to)

    @staticmethod
    def _can_retry_without_strict(exc):
        """Solo reintenta si el fallo apunta a un json_schema no soportado."""
        if isinstance(
            exc,
            (asyncio.TimeoutError, aiohttp.ClientConnectionError,
             aiohttp.ServerTimeoutError),
        ):
            return False
        status = getattr(exc, "status", None)
        if isinstance(status, int) and status not in _STRICT_RETRY_STATUSES:
            return False
        return True

    async def _generate(
        self,
        history,
        web_context,
        user,
        date_session,
        delta_max,
        extra_note=None,
        relationship_view=None,
        now=None,
        quick=False,
    ):
        now = self.clock() if now is None else now
        state = self.state
        points = state.entry_points(user.id)
        affinity_section = domain_prompts.affinity_prompt_section(
            points, affinity_level(points)[0], user.display_name
        )
        relationship_section = domain_prompts.relationship_status_section(
            state.world,
            state.users,
            user_id=user.id,
            display_name=user.display_name,
            now=now,
        )
        self_section = domain_prompts.self_model_prompt_section(
            state.world,
            notes=state.world.get("self_notes") or [],
        )
        if quick:
            # Turno breve: tono, relación y yo. Sin diario, memorias, usuarios
            # conocidos ni explicación de etiquetas (el mensaje es corto y no
            # los necesita); esto recorta el prompt y acelera el prefill.
            sections = [
                affinity_section,
                relationship_section,
                domain_prompts.romantic_relationship_section(
                    relationship_view or {
                        "stage": "none",
                        "history": [],
                        "allowed_refs": [],
                        "pending": None,
                        "is_partner": False,
                    },
                    user.display_name,
                ),
                domain_prompts.preferences_prompt_section(state.world),
                domain_prompts.last_shutdown_prompt_section(state.world),
                domain_prompts.identity_tags_prompt_section(compact=True),
                self_section,
            ]
        else:
            sections = [
                affinity_section,
                relationship_section,
                domain_prompts.romantic_relationship_section(
                    relationship_view or {
                        "stage": "none",
                        "history": [],
                        "allowed_refs": [],
                        "pending": None,
                        "is_partner": False,
                    },
                    user.display_name,
                ),
                domain_prompts.preferences_prompt_section(state.world),
                domain_prompts.last_shutdown_prompt_section(state.world),
                domain_prompts.identity_tags_prompt_section(),
                domain_prompts.date_context_section(
                    date_session if isinstance(date_session, dict) else None
                ),
                self_section,
                domain_prompts.memories_prompt_section(
                    _read_only_memories(state.memories, user.id)
                ),
                domain_prompts.known_users_prompt_section(
                    state.users,
                    state.diary,
                    state.world,
                    user_id=user.id,
                    display_name=user.display_name,
                ),
                domain_prompts.diary_prompt_section(state.diary, user.id, now),
            ]
        # Nudge anti-encadenamiento: solo si el último turno de Airi cerró con
        # pregunta. Fuera de ese patrón devuelve "" y no añade nada.
        sections.append(domain_prompts.question_variety_nudge_section(history))
        if extra_note:
            sections.append(
                f"\n\n=== NOTA INTERNA DEL SISTEMA ===\n{extra_note}\n"
            )
        system_prompt = domain_prompts.build_system_prompt(
            web_context, sections, compact=quick
        )
        # Vista de inferencia: el historial canónico se envía etiquetado con la
        # identidad y la afinidad de cada interlocutor. La etiqueta se
        # reconstruye en cada inferencia (nunca se persiste en el historial).
        visible_history = (
            history[-QUICK_HISTORY_MESSAGES:] if quick else history
        )
        view = build_inference_history(
            visible_history,
            self._inference_resolver(getattr(user, "id", None)),
            users=state.users,
        )
        messages = [{"role": "system", "content": system_prompt}, *view]
        request_tokens = LLM_SHORT_MAX_TOKENS if quick else None
        if hasattr(self.llm, "chat_with_meta"):
            try:
                # Salida estricta: la gramática del servidor garantiza JSON
                # aunque el modelo quiera responder en texto plano.
                raw, meta = await self.llm.chat_with_meta(
                    messages,
                    schema=RESPONSE_SCHEMA,
                    strict_schema=True,
                    max_tokens=request_tokens,
                    disable_thinking=quick,
                )
            except Exception as exc:
                if not self._can_retry_without_strict(exc):
                    raise
                log.warning(
                    "La salida estricta no está soportada por el servidor; "
                    "se reintenta en modo json_object.",
                    exc_info=True,
                )
                raw, meta = await self.llm.chat_with_meta(
                    messages,
                    schema=RESPONSE_SCHEMA,
                    max_tokens=request_tokens,
                    disable_thinking=quick,
                )
        else:
            raw = await self.llm.chat(
                messages,
                schema=RESPONSE_SCHEMA,
                max_tokens=request_tokens,
                disable_thinking=quick,
            )
            meta = LLMMeta()
        output = parse_model_output(raw, delta_max=delta_max)
        # Red de seguridad anti-interrogatorio: en charla casual, si Airi ya
        # cerró con pregunta el turno anterior y vuelve a hacerlo, se pide UNA
        # regeneración sin cierre interrogativo (las citas quedan fuera: ahí la
        # conversación puede pedir respuestas).
        if (
            not isinstance(date_session, dict)
            and domain_prompts.last_assistant_reply_ended_with_question(history)
            and (output.reply or "").rstrip().endswith("?")
        ):
            close_repair_messages = [
                *messages,
                {"role": "user", "content": QUESTION_CLOSE_REPAIR_PROMPT},
            ]
            try:
                if hasattr(self.llm, "chat_with_meta"):
                    try:
                        fixed_raw, fixed_meta = await self.llm.chat_with_meta(
                            close_repair_messages,
                            schema=RESPONSE_SCHEMA,
                            strict_schema=True,
                            max_tokens=request_tokens,
                            disable_thinking=quick,
                        )
                    except Exception:
                        fixed_raw, fixed_meta = await self.llm.chat_with_meta(
                            close_repair_messages,
                            schema=RESPONSE_SCHEMA,
                            max_tokens=request_tokens,
                            disable_thinking=quick,
                        )
                else:
                    fixed_raw = await self.llm.chat(
                        close_repair_messages,
                        schema=RESPONSE_SCHEMA,
                        max_tokens=request_tokens,
                        disable_thinking=quick,
                    )
                    fixed_meta = LLMMeta()
                fixed = parse_model_output(fixed_raw, delta_max=delta_max)
                if (fixed.reply or "").strip():
                    raw = fixed_raw
                    meta = fixed_meta
                    output = fixed
                    # Última garantía determinista: si aun así cierra con
                    # pregunta, se recorta la oración interrogativa final.
                    if (output.reply or "").rstrip().endswith("?"):
                        trimmed = strip_trailing_question(output.reply)
                        if trimmed != output.reply:
                            output.reply = trimmed
            except Exception:
                log.warning("No se pudo reparar el cierre interrogatorio")

        # Reparaciones de calidad restantes (una regeneración cada una, si
        # produce material mejor que lo actual):
        # 1) Respuesta vacía: reintentar con aviso explícito antes de omitir.
        if not output.reply:
            repair = await self._repair_regenerate(
                messages, EMPTY_REPLY_REPAIR_PROMPT,
                delta_max=delta_max, max_tokens=request_tokens,
                disable_thinking=quick,
            )
            if repair is not None:
                raw, meta, output = repair
        # 2) Copia casi literal de un turno anterior: regenerar.
        elif reply_repeats_history(output.reply, history):
            repair = await self._repair_regenerate(
                messages, REPEAT_REPAIR_PROMPT,
                delta_max=delta_max, max_tokens=request_tokens,
                disable_thinking=quick,
            )
            if repair is not None:
                raw, meta, output = repair
        problem = disconnect_claim_problem(
            output.reply or "", bool(output.disconnect)
        )
        if problem:
            log.warning("Salida incoherente sobre la marcha: %s", problem)
            repair_messages = [
                *messages,
                {
                    "role": "user",
                    "content": f"{DISCONNECT_REPAIR_PROMPT}\n\nProblema: {problem}",
                },
            ]
            try:
                if hasattr(self.llm, "chat_with_meta"):
                    try:
                        repaired_raw, repaired_meta = await self.llm.chat_with_meta(
                            repair_messages,
                            schema=RESPONSE_SCHEMA,
                            strict_schema=True,
                            max_tokens=request_tokens,
                            disable_thinking=quick,
                        )
                    except Exception:
                        repaired_raw, repaired_meta = await self.llm.chat_with_meta(
                            repair_messages,
                            schema=RESPONSE_SCHEMA,
                            max_tokens=request_tokens,
                            disable_thinking=quick,
                        )
                else:
                    repaired_raw = await self.llm.chat(
                        repair_messages,
                        schema=RESPONSE_SCHEMA,
                        max_tokens=request_tokens,
                        disable_thinking=quick,
                    )
                    repaired_meta = LLMMeta()
                repaired = parse_model_output(repaired_raw, delta_max=delta_max)
                if not disconnect_claim_problem(
                    repaired.reply or "", bool(repaired.disconnect)
                ):
                    raw = repaired_raw
                    meta = repaired_meta
                    output = repaired
            except Exception:
                log.warning("No se pudo reparar la coherencia de la marcha")

        if not output.reply:
            return (
                system_prompt,
                raw if isinstance(raw, str) else None,
                meta,
                ModelOutput(
                    None, "none", "none", "none", 0,
                    "continue", "none", "none",
                ),
            )
        return system_prompt, raw if isinstance(raw, str) else None, meta, output

    async def _repair_regenerate(
        self, messages, note, *, delta_max, max_tokens, disable_thinking
    ):
        """Una regeneración de reparación. None si no produce reply utilizable.

        Reusa el mensaje completo del turno y añade el aviso correctivo al
        final. Mantiene el mismo esquema estricto de salida con retry json_object.
        Devuelve `(raw, meta, ModelOutput)` para que quien llama pueda actualizar
        también lo que se registra en la traza.
        """
        repair_messages = [*messages, {"role": "user", "content": note}]
        try:
            if hasattr(self.llm, "chat_with_meta"):
                try:
                    raw, meta = await self.llm.chat_with_meta(
                        repair_messages,
                        schema=RESPONSE_SCHEMA,
                        strict_schema=True,
                        max_tokens=max_tokens,
                        disable_thinking=disable_thinking,
                    )
                except Exception:
                    raw, meta = await self.llm.chat_with_meta(
                        repair_messages,
                        schema=RESPONSE_SCHEMA,
                        max_tokens=max_tokens,
                        disable_thinking=disable_thinking,
                    )
            else:
                raw = await self.llm.chat(
                    repair_messages,
                    schema=RESPONSE_SCHEMA,
                    max_tokens=max_tokens,
                    disable_thinking=disable_thinking,
                )
                meta = LLMMeta()
            fixed = parse_model_output(raw, delta_max=delta_max)
        except Exception:
            log.warning("La regeneración de reparación falló", exc_info=True)
            return None
        if fixed.reply and fixed.reply.strip():
            return raw, meta, fixed
        return None

    def _inference_resolver(self, recipient_id=None):
        """Resolver de afinidad para la vista de inferencia.

        Solo se expone la afinidad del destinatario del turno: el resto de
        interlocutores aparecen como desconocidos (`affinity=unknown`), de modo
        que Airi no arrastre el vínculo ni el tono de otra persona. Un usuario
        sin registro devuelve afinidad desconocida (neutral), NUNCA un cero
        inventado.
        """
        affinity = dict(self.state.affinity)
        recipient = str(recipient_id) if recipient_id is not None else None
        scope = self.affinity_scope

        def resolve(user_id, _name):
            if user_id is None:
                return AffinityInfo()
            if scope == "recipient" and recipient is not None and str(user_id) != recipient:
                return AffinityInfo()
            entry = affinity.get(str(user_id))
            if isinstance(entry, dict):
                points = entry_points(entry)
                return AffinityInfo(points=points, level=affinity_level(points)[0])
            return AffinityInfo()

        return resolve

    @staticmethod
    def _emit_trace(ctx, trace):
        if ctx.on_trace is not None:
            try:
                ctx.on_trace(trace)
            except Exception:
                log.exception("El hook on_trace falló; se ignora")

    async def _build_search_query(self, user_message):
        try:
            content = await self.llm.chat(
                [
                    {"role": "system", "content": SEARCH_QUERY_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=SEARCH_QUERY_MAX_TOKENS,
                temperature=0.2,
            )
            query = content.strip().strip('"').strip("'").strip()
            if query:
                query = query.splitlines()[0].strip()
            query = query[:300]
            return query or user_message
        except Exception:
            log.exception(
                "No se pudo reformular la consulta; se usará el mensaje original"
            )
            return user_message

    def _register_user(self, who, now):
        is_new = domain_users.register_activity(
            self.state.users,
            user_id=who.id,
            display_name=who.display_name,
            now=now,
        )
        if is_new:
            log.info("Nuevo usuario conocido: %s (%s)", who.display_name, who.id)
            self.state.log_diary_event(
                "meet",
                who,
                f"Hoy he conocido a {who.display_name} por primera vez.",
            )
        self.state.save_users()

    def _add_diary_reflection(self, user_id, text, now):
        """Reflexión en 1ª persona del diario, con dedup y cooldown."""
        text = clean_reply(text).strip()[:200].strip()
        if not text:
            return False
        key = str(user_id)
        recent = [
            e for e in self.state.diary[-20:]
            if isinstance(e, dict) and e.get("kind") == "reflection"
            and str(e.get("user_id")) == key
        ]
        lower = text.lower()
        if any(lower == str(e.get("text", "")).lower() for e in recent):
            log.info("Reflexión duplicada descartada para %s", user_id)
            return False
        if (
            recent
            and now - float(recent[-1].get("ts", 0.0) or 0.0) < DIARY_REFLECTION_MIN_INTERVAL
        ):
            return False
        entry = new_diary_entry(
            "reflection",
            user_id,
            self.state.display_name(user_id),
            text,
            now,
            season=int(self.state.world.get("season", 1) or 1),
        )
        if add_diary_entry(self.state.diary, entry):
            self.state.save_diary()
            log.info("Reflexión guardada para %s: %r", user_id, text)
            return True
        return False



