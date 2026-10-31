"""Servicio de conversación: un turno completo sin Discord ni HTTP directo."""

from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Callable

import aiohttp

from airi.config import Settings
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
    LLM_REASONING_BUDGET_HIGH_TOKENS,
    LLM_REASONING_BUDGET_LOW_TOKENS,
    LLM_REASONING_BUDGET_MEDIUM_TOKENS,
    LLM_SHORT_MAX_TOKENS,
    MAX_HISTORY_MESSAGES,
    QUICK_HISTORY_MESSAGES,
    QUICK_REPLY_MAX_CHARS,
)
from airi.domain.diary import add_diary_entry, new_diary_entry
from airi.domain.gifs import ALLOWED_GIF_TYPES
from airi.domain.grounding import reply_seems_grounded
from airi.domain.history_tags import AffinityInfo, build_inference_history, normalize_name
from airi.domain.llm_output import (
    RESPONSE_SCHEMA,
    SESSION_RESPONSE_SCHEMA,
    ModelOutput,
    assistant_history_content,
    assistant_reply_text,
    extract_json_object,
    parse_model_output,
    parse_session_output,
    response_schema,
)
from airi.domain.narrative_claims import (
    disconnect_claim_problem,
    strip_leaving_claims,
)
from airi.domain.notices import (
    level_up_notice,
    meet_notice,
    memory_saved_notice,
    relationship_confirmed_notice,
    relationship_proposed_notice,
    self_changed_notice,
)
from airi.domain.reactions import is_negative_reaction
from airi.domain.relationship_claims import (
    relationship_claim_problem,
    soften_relationship_claims,
)
from airi.domain.relationships import RelationshipFingerprint
from airi.domain.self_model import apply_self_update
from airi.domain.text_filters import (
    clean_reply,
    limit_narrative_actions,
    strip_repetition_loop,
    strip_trailing_questions,
)
from airi.domain.time_perception import TimeConfig, build_temporal_context
from airi.domain.turn_guard import DateFingerprint, fingerprint_of
from airi.domain.turn_quality import (
    QualityIssue,
    ReviewResult,
    merge_issues,
    parse_review,
    quality_issues,
    reply_repeats_history,  # noqa: F401 - reexported for compatibility/tests
    token_overlap,
)
from airi.domain.web import detect_search_intent, recent_topic_terms
from airi.domain.web_tool import note_years
from airi.logging_setup import (
    get_logger,
    reset_correlation_id,
    set_correlation_id,
)
from airi.observability import jsonl_events as jl
from airi.observability.interaction_tracker import current_tracker
from airi.observability.trace import TurnEvent
from airi.observability.trace_store import TraceStore
from airi.ports.llm import LLMMeta
from airi.services.relationships import RelationshipService
from airi.services.state import AppState
from airi.services.web_search import WebSearchOutcome, WebSearchService

log = get_logger(__name__)

# Ventana de conversación que se ofrece a la decisión de búsqueda. Sin ella,
# una corrección como "puedes buscarlo" no contiene las entidades en disputa.
SEARCH_CONTEXT_MESSAGES = 10
SEARCH_CONTEXT_ENTRY_MAX_CHARS = 300
SEARCH_CONTEXT_TOTAL_MAX_CHARS = 2000


def _search_query_context(history, snapshot=()):
    """Contexto reciente legible para construir una query con sentido."""
    lines = []
    for entry in list(history or ())[-SEARCH_CONTEXT_MESSAGES:]:
        if not isinstance(entry, dict):
            continue
        if entry.get("role") == "assistant":
            speaker = "Airi"
            text = assistant_reply_text(entry.get("content"))
        else:
            speaker = entry.get("author_name") or "Usuario"
            text = str(entry.get("content") or "")
        text = " ".join(text.split())
        if text:
            lines.append(f"{speaker}: {text[:SEARCH_CONTEXT_ENTRY_MAX_CHARS]}")
    for entry in snapshot or ():
        if isinstance(entry, dict):
            speaker = entry.get("author_name") or "Usuario"
            text = entry.get("content") or ""
        else:
            speaker = getattr(entry, "author_name", "") or "Usuario"
            text = getattr(entry, "content", "") or ""
        text = " ".join(str(text).split())
        if text:
            lines.append(f"{speaker}: {text[:SEARCH_CONTEXT_ENTRY_MAX_CHARS]}")
    return "\n".join(lines)[-SEARCH_CONTEXT_TOTAL_MAX_CHARS:]


def _last_assistant_text(history):
    """Última respuesta legible de Airi en el historial previo."""
    for entry in reversed(history or ()):
        if not isinstance(entry, dict) or entry.get("role") != "assistant":
            continue
        return assistant_reply_text(entry.get("content")) or ""
    return ""


def _last_user_text(history):
    """Último mensaje del usuario en el historial previo."""
    for entry in reversed(history or ()):
        if not isinstance(entry, dict) or entry.get("role") != "user":
            continue
        return " ".join(str(entry.get("content") or "").split())
    return ""


def _previous_user_text(history, messages):
    """Último mensaje del usuario anterior a los mensajes de este turno."""
    prior = list(history or ())
    count = len(messages or ())
    if count:
        prior = prior[:-count]
    return _last_user_text(prior)


def _recent_topic_terms_for_turn(
    state,
    channel_id,
    *,
    history=(),
    snapshot=(),
    current_text="",
    exclude_names=(),
    limit=8,
):
    """Entidades recientes que sirven de ancla para la búsqueda.

    Los ``turn_records`` conservan respuestas de Airi que ya salieron de la
    ventana corta de historial. Sin ellos, un tema mencionado hace diez turnos
    desaparecía de la query. Solo se usan como pistas de tema, no como hechos.
    """
    texts = []
    records = getattr(state, "turn_records", None) or {}
    prefix = f"{channel_id}:"
    channel_records = [
        record
        for key, record in records.items()
        if isinstance(record, dict) and str(key).startswith(prefix)
    ]
    channel_records.sort(
        key=lambda record: float(
            record.get("updated_at") or record.get("created_at") or 0.0
        )
    )
    for record in channel_records[-12:]:
        reply_text = record.get("reply_text")
        if reply_text:
            texts.append(str(reply_text))
    for entry in snapshot or ():
        if isinstance(entry, dict):
            content = entry.get("content")
        else:
            content = getattr(entry, "content", "")
        if content:
            texts.append(str(content))
    for entry in list(history or ())[-4:]:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        if entry.get("role") == "assistant":
            content = assistant_reply_text(content)
        if content:
            texts.append(str(content))
    if current_text:
        texts.append(str(current_text))
    return recent_topic_terms(
        texts, exclude_names=exclude_names, limit=limit
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


PARSE_REPAIR_PROMPTS = {
    "truncation": (
        "La generación anterior se agotó antes de completar la respuesta. "
        "Responde brevemente, ve directo al objeto JSON completo, incluye un "
        "reply natural para el último mensaje y cierra el JSON. No añadas texto externo."
    ),
    "empty": (
        "La respuesta anterior llegó vacía o sin reply legible. Devuelve un "
        "objeto JSON completo con un reply breve, natural y nuevo que reaccione "
        "al último mensaje. No añadas texto externo."
    ),
    "invalid_json": (
        "La salida anterior no se pudo interpretar como JSON utilizable. "
        "Devuelve únicamente el objeto JSON completo requerido."
    ),
}
QUALITY_REPAIR_PROMPT = (
    "Revisa tu borrador según los problemas y evidencias indicados. Corrige "
    "solo lo necesario, conserva el resto de la respuesta, tu voz y el hilo. "
    "No menciones esta corrección ni te disculpes por ella. Devuelve únicamente "
    "el objeto JSON completo del esquema.\n"
)
CONVERSATION_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "on_topic": {"type": "boolean"},
        "right_addressee": {"type": "boolean"},
        "coherent": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["off_topic", "wrong_addressee", "nonsense", "self_reset"],
                    },
                    "impact": {
                        "type": "string",
                        "enum": ["breaks_thread", "wrong_person", "incoherent", "self_reset"],
                    },
                    "evidence": {"type": "string"},
                },
                "required": ["kind", "impact", "evidence"],
            },
        },
    },
    "required": ["on_topic", "right_addressee", "coherent", "issues"],
}
CONVERSATION_REVIEW_SYSTEM_PROMPT = (
    "Eres un evaluador neutral de coherencia conversacional. No escribas una "
    "respuesta ni juzgues el estilo. Compara el borrador con el hilo reciente. "
    "Aprueba por defecto: marca solo fallos claros de tema, destinatario, "
    "coherencia o reinicio de identidad. Cada issue debe incluir una cita "
    "literal del borrador; sin cita, no hay issue. Ante la duda, aprueba. "
    "Devuelve solo un objeto JSON con estas claves: "
    '"on_topic" (boolean), "right_addressee" (boolean), "coherent" (boolean), '
    '"issues" (array de objetos con "kind" (enum: off_topic, wrong_addressee, '
    'nonsense, self_reset), "impact" (enum: breaks_thread, wrong_person, '
    'incoherent, self_reset) y "evidence" (cita literal del borrador)).'
)


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


def _read_only_memories(memories, user_id) -> list:
    """Vista de memorias que no crea una entrada vacía durante la generación."""
    entries = memories.get(str(user_id)) if isinstance(memories, dict) else None
    return list(entries) if isinstance(entries, list) else []


@dataclass(frozen=True)
class RepairOutcome:
    raw: str
    meta: LLMMeta
    output: ModelOutput
    stay_active: bool | None = None
    accepted: bool = True
    reason: str = ""


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
    # Modo espectador: captura efímera del buffer pasivo del canal.
    spectator_reason: str = ""
    spectator_snapshot: tuple = ()  # entradas del buffer pasivo (dicts).
    spectator_roll: float = 0.0
    # Modo de conversación de sesión (normal | spectator | active | proactive).
    conversation_mode: str = "normal"
    conversation_reason: str = ""
    spectator_roll: float = 0.0
    # Selector experimental, independiente del camino rápido de producción.
    system_prompt_variant: domain_prompts.PromptVariant = "current"
    # Streaming se activa exclusivamente para el runner de benchmark.
    stream_llm: bool = False
    # Override opcional exclusivo de evaluaciones/controladores explícitos.
    llm_max_tokens: int | None = None


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
    stay_active: bool = True
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
    stay_active: bool = True
    # Señales deterministas del turno (búsqueda, tema y reacción negativa).
    search_intent: str | None = None
    topic_terms: tuple = ()
    negative_reaction: bool = False


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
        time_config: TimeConfig | None = None,
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
        settings = Settings.from_env()
        self.conversation_review_enabled = settings.conversation_review
        self.web_search_enabled = settings.web_search
        self.web_search = WebSearchService(
            llm=llm, search=search, notifier=notifier
        )
        self.time_config = time_config or TimeConfig(
            enabled=settings.time_context,
            timezone=settings.timezone,
        )
        # Almacén de eventos: por defecto el del AppState.
        self.traces = traces if traces is not None else getattr(state, "traces", None)
        # Estado romántico por usuario (etapas, evidencia y propuestas).
        self.relationships = RelationshipService(state)
        self._logger = None
        self._interaction_id = None

    def _active_tracker(self):
        tracker = current_tracker()
        if tracker is not None:
            return tracker
        return self._logger

    def _start_logging(self, correlation_id: str) -> None:
        if self._logger is not None:
            return
        tracked = current_tracker()
        if tracked is not None:
            self._logger = tracked
            return
        self._logger = jl.JsonlInteractionLogger(
            correlation_id, catalog=jl.DEFAULT_CATALOG
        )
        self._logger.start()

    def _finish_interaction(self) -> None:
        tracked = current_tracker()
        if self._logger is not None and self._logger is tracked:
            # El ciclo de vida lo gestiona el contexto tracked_interaction.
            self._logger = None
            return
        if self._logger is None:
            return
        try:
            self._logger.summary()
        except Exception:
            log.exception(
                "No se pudo emitir el resumen de la interacción de conversación"
            )
        self._logger = None

    def _log_module(self, module: str, status: str, **state) -> None:
        tracker = self._active_tracker()
        if tracker is not None:
            tracker.module_result(module, status, **state)

    async def generate_turn(self, user, messages, ctx: TurnContext) -> TurnDraft:
        """Genera una respuesta sin mutar el estado de dominio."""
        import time as _time

        cid = ctx.correlation_id or uuid.uuid4().hex[:12]
        token = set_correlation_id(cid)
        self._start_logging(cid)
        self._log_module("conversation", "activated")
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
            web_allowed = (
                ctx.allow_web
                and not in_date
                and ctx.kind not in {"spectator", "active", "proactive"}
                and getattr(ctx, "conversation_mode", "normal")
                not in {"spectator", "active", "proactive"}
            )
            ev.allow_web = web_allowed
            if in_date:
                history = list(date_session.get("history") or [])
            else:
                history = list(self.state.histories.get(ctx.channel_id, []))
            # Vista previa a añadir el mensaje actual: la intención de búsqueda
            # y la query no deben repetir el texto que ya se pasa aparte.
            prior_history = list(history)
            for who, part in messages:
                if getattr(ctx, "conversation_mode", "") == "proactive" and not (part or "").strip():
                    continue
                history.append({
                    "role": "user",
                    "content": part,
                    "author_id": str(who.id),
                    "author_name": getattr(who, "display_name", None),
                    "ts": float(now),
                })
            ev.history_in = list(history)

            try:
                temporal = build_temporal_context(
                    now,
                    self.time_config,
                    users=self.state.users,
                    history=prior_history,
                    snapshot=ctx.spectator_snapshot,
                    user_id=uid,
                    in_date=in_date,
                )
            except Exception as exc:
                temporal = None
                ev.errors.append({
                    "module": "time_perception",
                    "error_type": type(exc).__name__,
                })
            ev.time_context = {"enabled": bool(self.time_config.enabled)}
            if temporal is not None:
                ev.time_context.update({
                    "timezone": self.time_config.timezone,
                    "local_iso": temporal.moment.local_iso,
                    "weekday": temporal.moment.weekday,
                    "bucket": temporal.moment.bucket,
                    "minutes_since_user": (
                        int(temporal.user_gap_seconds // 60)
                        if temporal.user_gap_seconds is not None
                        else None
                    ),
                    "minutes_since_channel": (
                        int(temporal.channel_gap_seconds // 60)
                        if temporal.channel_gap_seconds is not None
                        else None
                    ),
                })

            # Modo espectador: la captura efímera del buffer pasivo se inyecta
            # EN el prompt (y solo en la traza), nunca en el historial
            # persistido; los mensajes pasivos mueren con su TTL.
            prompt_history = history
            if ctx.kind == "spectator" and ctx.spectator_snapshot:
                ephemeral = []
                for entry in ctx.spectator_snapshot:
                    if isinstance(entry, dict):
                        author_name = entry.get("author_name") or ""
                        content = entry.get("content") or ""
                        timestamp = entry.get("ts")
                    else:
                        author_name = getattr(entry, "author_name", "")
                        content = getattr(entry, "content", "")
                        timestamp = getattr(entry, "ts", None)
                    observed = {
                        "role": "user",
                        "content": content,
                        "author_id": str(getattr(entry, "author_id", "") or ""),
                        "author_name": author_name,
                        "spectator": True,
                    }
                    if timestamp is not None:
                        observed["ts"] = timestamp
                    ephemeral.append(observed)
                ev.spectator_reason = ctx.spectator_reason
                ev.spectator_snapshot = [
                    entry if isinstance(entry, dict) else vars(entry)
                    for entry in ctx.spectator_snapshot
                ]
                ev.spectator_probability_roll = ctx.spectator_roll
                prompt_history = [*history, *ephemeral]

            log.info("turno user=%s in_date=%s", uid, in_date)

            web_context = None
            search_query = None
            search_intent = None
            search_failed = False
            exclude_names = (
                "Airi",
                getattr(user, "display_name", ""),
            )
            # El detector léxico ya no decide búsquedas: solo alimenta la
            # memoria de correcciones. La búsqueda la decide el modelo con
            # tool calling; aquí no se usa para disparar nada.
            search_intent = detect_search_intent(
                merged_text,
                history=prior_history,
                snapshot=ctx.spectator_snapshot,
                exclude_names=exclude_names,
            )
            if search_intent != "correction":
                search_intent = None
            topic_terms = ()
            if search_intent:
                topic_terms = _recent_topic_terms_for_turn(
                    self.state,
                    ctx.channel_id,
                    history=prior_history,
                    snapshot=ctx.spectator_snapshot,
                    current_text=merged_text,
                    exclude_names=exclude_names,
                )
            negative_reaction = is_negative_reaction(merged_text)

            extra_note = ctx.extra_note
            preference_correction = (
                domain_memories.extract_preference_correction(merged_text)
            )
            if preference_correction:
                preference_note = (
                    "=== CORRECCIÓN DE PREFERENCIA (PRIORIDAD) ===\n"
                    "La persona corrige una preferencia. La versión vigente es: "
                    f"{preference_correction.memory_text}\n"
                    "Responde usando esa versión; no repitas el dato anterior ni "
                    "lo contradigas. Si la pregunta actual es sobre ese tema, "
                    "contéstala directamente antes de preguntar cualquier otra cosa."
                )
                extra_note = "\n\n".join(
                    part for part in (extra_note, preference_note) if part
                )
            if not preference_correction:
                relevant = domain_memories.relevant_memories(
                    _read_only_memories(self.state.memories, uid), merged_text
                )
                if relevant:
                    relevant_note = (
                        "=== MEMORIA RELEVANTE ===\n"
                        + "\n".join(f"- {entry.get('text', '')}" for entry in relevant)
                        + "\nUsa esta información para responder a lo que se te "
                        "pregunta; no la contradigas ni inventes otro dato distinto."
                    )
                    extra_note = "\n\n".join(
                        part for part in (extra_note, relevant_note) if part
                    )
            if search_intent == "correction":
                previous_claim = _last_assistant_text(prior_history)
                topics_text = (
                    ", ".join(topic_terms[:4]) or "el tema de la conversación"
                )
                correction_note = (
                    "=== CORRECCIÓN DEL USUARIO (PRIORIDAD) ===\n"
                    "La persona corrige un dato. Su corrección prevalece sobre "
                    "cualquier respuesta anterior de Airi; el historial propio "
                    "no es una fuente de verdad.\n"
                    f"Tema/entidades: {topics_text}\n"
                    "Lo que dijo Airi antes (posiblemente erróneo): "
                    f"{previous_claim[:300] or '(nada)'}\n"
                    f"Corrección del usuario: {merged_text[:300]}\n"
                    "No repitas la afirmación corregida. Si no tienes el dato "
                    "correcto, dilo con honestidad."
                )
                extra_note = "\n\n".join(
                    part for part in (extra_note, correction_note) if part
                )

            web_outcome = WebSearchOutcome()
            if web_allowed and self.web_search_enabled:
                t0 = _time.perf_counter()
                self._log_module("web_search", "activated")
                web_outcome = await self.web_search.run(
                    current_text=merged_text,
                    context=_search_query_context(
                        prior_history, ctx.spectator_snapshot
                    ),
                )
                timings["search_ms"] = int((_time.perf_counter() - t0) * 1000)
                if web_outcome.error:
                    self._log_module(
                        "web_search",
                        "failed",
                        error_message=web_outcome.error,
                    )
                elif web_outcome.requested:
                    self._log_module(
                        "web_search",
                        "activated",
                        reason="tool_call",
                        query=web_outcome.request.query,
                        results=bool(
                            web_outcome.notes and not web_outcome.notes.is_empty
                        ),
                    )
                else:
                    self._log_module(
                        "web_search",
                        "skipped",
                        reason_code="model_declined",
                    )
            web_context = web_outcome.prompt_block
            search_query = (
                web_outcome.request.query if web_outcome.request else None
            )
            search_failed = (
                web_outcome.failed if web_outcome.requested else False
            )
            ev.search_query = search_query
            ev.web_query = search_query
            ev.web_context = web_context
            ev.web_relevant = (
                None if not web_outcome.requested else not web_outcome.failed
            )
            ev.web_requested = web_outcome.requested
            ev.web_motivo = (
                web_outcome.request.motivo if web_outcome.request else None
            )
            ev.web_tool_backend = (
                "native" if web_allowed and self.web_search_enabled else None
            )
            ev.web_decision_ms = web_outcome.decision_ms
            ev.web_search_ms = web_outcome.search_ms
            ev.web_notice_sent = web_outcome.notice_sent
            ev.web_error = web_outcome.error
            ev.web_note_years = (
                list(note_years(web_outcome.notes))
                if web_outcome.notes is not None
                else []
            )

            delta_max = self.date_delta_max if in_date else AFFINITY_DELTA_MAX
            quick = self._is_quick_turn(
                merged_text,
                in_date=in_date,
                web_context=web_context,
                kind=ctx.kind,
                extra_note=extra_note,
                history=history,
                user=uid,
                display_name=getattr(user, "display_name", None),
            )
            t0 = _time.perf_counter()
            self._log_module("llm_call", "activated")
            try:
                (
                    system_prompt, raw_llm, meta, output, stay_active, llm_calls,
                    repair_telemetry,
                ) = await self._generate(
                    prompt_history, web_context, user, date_session, delta_max,
                    extra_note=extra_note,
                    relationship_view=relationship_view,
                    now=now,
                    quick=quick,
                    prompt_variant=ctx.system_prompt_variant,
                    stream_llm=ctx.stream_llm,
                    max_tokens_override=ctx.llm_max_tokens,
                    conversation_mode=getattr(ctx, "conversation_mode", "normal"),
                    conversation_reason=getattr(ctx, "conversation_reason", ""),
                    turn_kind=getattr(ctx, "kind", "message"),
                    temporal=temporal,
                )
            except Exception as exc:
                self._log_module(
                    "llm_call",
                    "failed",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                raise
            self._log_module(
                "llm_call",
                "activated",
                duration_ms=int((_time.perf_counter() - t0) * 1000),
            )
            timings["llm_ms"] = int((_time.perf_counter() - t0) * 1000)
            ev.prompt_system = system_prompt
            ev.raw_llm = raw_llm
            ev.llm_latency_ms = timings["llm_ms"]
            ev.llm_ms = timings["llm_ms"]
            ev.llm_finish_reason = meta.finish_reason
            ev.llm_usage = meta.usage
            ev.llm_ttft_ms = meta.ttft_ms
            ev.llm_first_content_ms = meta.first_content_ms
            ev.llm_server_timings = meta.server_timings
            ev.llm_reasoning_present = meta.reasoning_present
            ev.llm_reasoning_tokens = meta.reasoning_tokens
            ev.llm_calls = llm_calls
            ev.review_on_topic = repair_telemetry["review_on_topic"]
            ev.review_issues = repair_telemetry["review_issues"]
            ev.review_ms = repair_telemetry["review_ms"]
            ev.repair_exhausted = repair_telemetry["repair_exhausted"]
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
            # La repetición literal se filtra antes mediante quality_repair;
            # aquí solo se cortan bucles degenerados dentro del propio texto.
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
                    search_intent=search_intent,
                    topic_terms=tuple(topic_terms),
                    negative_reaction=negative_reaction,
                )

            # El grounding es una señal de observabilidad, no un juez: ya no
            # sustituye la respuesta ni le impone una frase a Airi.
            grounded = True
            if web_outcome.requested:
                if search_failed:
                    grounded = False
                elif web_context:
                    grounded = reply_seems_grounded(answer, web_context)
                if not grounded:
                    log.info(
                        "Grounding marcó la respuesta como no fundamentada; "
                        "se conserva la voz del modelo y queda en traza."
                    )
            ev.grounded = grounded
            ev.web_grounded = grounded if web_outcome.requested else None
            self._log_module(
                "grounding",
                "activated",
                grounded=grounded,
                telemetry_only=web_outcome.requested,
            )
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
                stay_active=stay_active,
                gif_bytes=gif_bytes,
                web_context=web_context,
                grounded=grounded,
                timings=timings,
                trace=ev,
                relationship_fingerprint=relationship_fingerprint,
                search_intent=search_intent,
                topic_terms=tuple(topic_terms),
                negative_reaction=negative_reaction,
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

        new_users = []
        for who, _part in draft.messages:
            if self._register_user(who, draft.now):
                new_users.append(who)

        uid = draft.user.id
        notices = [
            meet_notice(
                self.state.display_name(who.id),
                user_id=str(who.id),
            )
            for who in new_users
        ]
        proactive = getattr(draft.context, "kind", "") == "proactive"
        date_session = self.state.dates.get(str(uid))
        in_date = draft.date_fingerprint is not None and isinstance(date_session, dict)
        entry = self.state.affinity_entry(uid)
        level_before = affinity_level(entry_points(entry))[0]
        output = draft.output
        answer = draft.answer
        disconnect_reason = (
            output.disconnect.get("reason") if output.disconnect else None
        )
        if ev is not None:
            ev.disconnect = output.disconnect
            ev.stay_active = getattr(draft, "stay_active", True)

        delta_to_apply = output.affinity_delta
        if draft.context.suppress_affinity:
            if delta_to_apply:
                log.info("El turno no mueve la afinidad (ya aplicada por el sistema).")
            delta_to_apply = 0
        if draft.negative_reaction and delta_to_apply > 0:
            log.info(
                "Afinidad positiva ignorada: el mensaje es una negación o "
                "corrección directa."
            )
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
            notices.append(
                level_up_notice(
                    self.state.display_name(uid),
                    level_after,
                    user_id=str(uid),
                )
            )
        log.info(
            "afinidad %+d (aplicado %+d) total=%d (%s→%s)",
            output.affinity_delta, applied, points_now, level_before, level_after,
        )

        diary_saved = False
        if (not proactive) and leveled_up and output.diary.lower() != "none":
            diary_saved = self._add_diary_reflection(uid, output.diary, draft.now)
        if diary_saved:
            self._log_module("diary", "activated", diary_saved=True)
        else:
            self._log_module("diary", "skipped", reason_code="not_requested")
        memory_saved = False
        memory_saved_text = ""
        message_text = " ".join(
            " ".join(str(part).split()) for _, part in draft.messages
        )
        preference_correction = (
            domain_memories.extract_preference_correction(message_text)
        )
        memory_action = output.memory
        if preference_correction:
            log.info(
                "Memoria del modelo ignorada: hay una corrección explícita de "
                "preferencia y prevalece la versión vigente."
            )
            memory_action = "none"
        if (
            draft.negative_reaction
            and isinstance(memory_action, str)
            and not memory_action.lower().startswith("olvidar:")
        ):
            log.info(
                "Memoria del modelo ignorada: el mensaje es una negación o "
                "corrección directa."
            )
            memory_action = "none"
        if not proactive:
            memory_saved = domain_memories.process_memory_action(
                self.state.memories,
                uid,
                memory_action,
                now=draft.now,
                source="message",
                source_text=message_text,
                turn_key=draft.context.turn_key,
            )
            if memory_saved:
                memory_saved_text = str(memory_action)
            if preference_correction and domain_memories.apply_preference_correction(
                self.state.memories,
                uid,
                preference_correction,
                now=draft.now,
                source="correction",
                source_text=message_text,
                previous_text=_previous_user_text(
                    draft.history, draft.messages
                ),
                turn_key=draft.context.turn_key,
            ):
                memory_saved = True
                memory_saved_text = preference_correction.memory_text
        correction_text = ""
        if not proactive and draft.search_intent == "correction":
            message_text_short = message_text[:160]
            topics = ", ".join(draft.topic_terms[:3]) or "un dato factual"
            display_name = (
                getattr(draft.user, "display_name", None) or "El usuario"
            )
            correction_text = (
                f"{display_name} me corrigió sobre {topics}: {message_text_short}"
            )
            if domain_memories.add_memory(
                self.state.memories,
                uid,
                correction_text,
                now=draft.now,
                source="correction",
                source_text=message_text,
                turn_key=draft.context.turn_key,
            ):
                memory_saved = True
                memory_saved_text = correction_text
        self._log_module("memory", "activated", memory_saved=memory_saved)
        if memory_saved:
            self.state.save_memories()
            notices.append(memory_saved_notice(user_id=str(uid)))

        # Deriva lenta: si han pasado los días configurados, los rasgos se
        # acercan un paso a su base. Es idempotente y no toca el núcleo.
        self.state.decay_self(now=draft.now)

        self_changed = False
        self_entry = None
        if (not proactive) and output.self_update:
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
                self.state.save_identity()
                notices.append(self_changed_notice(user_id=str(uid)))

        # Relación afectiva: el modelo propone y el dominio decide dentro del
        # mismo commit que la afinidad y el resto de efectos del turno.
        relationship_outcome = None
        if not proactive:
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
            self._log_module("relationships", "activated")
        else:
            from airi.services.relationships import RelationshipOutcome

            relationship_outcome = RelationshipOutcome()
            self._log_module("relationships", "skipped", reason_code="proactive_turn")
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
        display_name = self.state.display_name(uid)
        if relationship_outcome.action_applied == "propose":
            notices.append(
                relationship_proposed_notice(
                    display_name,
                    user_id=str(uid),
                )
            )
        if relationship_outcome.partner_confirmed:
            notices.append(
                relationship_confirmed_notice(
                    display_name,
                    user_id=str(uid),
                )
            )

        history = list(draft.history)
        if proactive:
            history.append({
                "role": "assistant",
                "content": assistant_history_content(answer, output),
                "author_id": "",
                "author_name": "",
                "reply_to_user_id": "",
                "reply_to_user_name": None,
                "system_generated": True,
                "ts": float(draft.now),
            })
        else:
            history.append({
                "role": "assistant",
                "content": assistant_history_content(answer, output),
                "reply_to_user_id": str(uid),
                "reply_to_user_name": getattr(draft.user, "display_name", None),
                "ts": float(draft.now),
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
        ev.memory_saved = (
            memory_saved_text
            if memory_saved_text
            else (output.memory if memory_saved else None)
        )
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
            stay_active=getattr(draft, "stay_active", True),
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
            self._finish_interaction()
            raise
        await self.finish_trace(ctx, result.trace)
        for notice in result.notices:
            if self.notifier is not None:
                try:
                    await self.notifier.send(notice)
                except Exception:
                    log.warning("No se pudo enviar el aviso post-turno")
        self._finish_interaction()
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

    async def _chat(
        self,
        calls,
        purpose,
        messages,
        *,
        schema,
        max_tokens,
        reasoning_budget_tokens=None,
        quick_turn=False,
        stream_llm=False,
        repair_reason=None,
    ):
        """Una invocación al modelo, registrada en `calls` con su propósito.

        Encapsula el reintento de `json_schema` a `json_object` para que la
        traza refleje cuántas peticiones se hicieron de verdad y por qué.
        """
        stream_kwargs = {"stream": True} if stream_llm else {}
        # Cada reparación solicita presupuesto bajo, sin apagar reasoning. El
        # override queda acotado a esta petición y no cambia el modo global.
        is_repair = purpose != "primary"
        requested_reasoning_budget = (
            LLM_REASONING_BUDGET_LOW_TOKENS
            if is_repair
            else reasoning_budget_tokens
        )
        requested_quick_turn = bool(quick_turn and not is_repair)
        if not hasattr(self.llm, "chat_with_meta"):
            if stream_llm:
                raise RuntimeError(
                    "El cliente LLM no soporta metadata necesaria para streaming"
                )
            started = time.perf_counter()
            try:
                raw = await self.llm.chat(
                    messages,
                    schema=schema,
                    max_tokens=max_tokens,
                    reasoning_budget_tokens=requested_reasoning_budget,
                    quick_turn=requested_quick_turn,
                )
            except Exception as exc:
                self._record_call(
                    calls, purpose, None, started, max_tokens,
                    requested_reasoning_budget, requested_quick_turn,
                    status="failed", error_type=type(exc).__name__,
                    repair_reason=repair_reason,
                )
                raise
            meta = LLMMeta()
            self._record_call(
                calls, purpose, meta, started, max_tokens,
                requested_reasoning_budget, requested_quick_turn,
                repair_reason=repair_reason,
            )
            return raw, meta
        started = time.perf_counter()
        try:
            # Salida estricta: la gramática del servidor garantiza JSON aunque
            # el modelo quiera responder en texto plano.
            raw, meta = await self.llm.chat_with_meta(
                messages,
                schema=schema,
                strict_schema=True,
                max_tokens=max_tokens,
                reasoning_budget_tokens=requested_reasoning_budget,
                quick_turn=requested_quick_turn,
                **stream_kwargs,
            )
        except Exception as exc:
            self._record_call(
                calls, purpose, None, started, max_tokens,
                requested_reasoning_budget, requested_quick_turn,
                status="failed", error_type=type(exc).__name__,
                repair_reason=repair_reason,
            )
            if not self._can_retry_without_strict(exc):
                raise
            log.warning(
                "La salida estricta no está soportada por el servidor; "
                "se reintenta en modo json_object.",
                exc_info=True,
            )
            started = time.perf_counter()
            raw, meta = await self.llm.chat_with_meta(
                messages,
                schema=schema,
                max_tokens=max_tokens,
                reasoning_budget_tokens=requested_reasoning_budget,
                quick_turn=requested_quick_turn,
                **stream_kwargs,
            )
            self._record_call(
                calls, f"{purpose}:json_object_retry", meta, started,
                max_tokens, requested_reasoning_budget, requested_quick_turn,
                repair_reason=repair_reason,
            )
            return raw, meta
        self._record_call(
            calls, purpose, meta, started, max_tokens,
            requested_reasoning_budget, requested_quick_turn,
            repair_reason=repair_reason,
        )
        return raw, meta

    def _record_call(
        self, calls, purpose, meta, started, max_tokens, reasoning_budget_tokens,
        quick_turn=False, *, status="ok", error_type=None, repair_reason=None,
    ):
        """Añade a `calls` solo metadatos: nunca prompt, content ni reasoning."""
        if calls is None:
            return
        effective_max = max_tokens
        if effective_max is None:
            effective_max = getattr(self.llm, "max_output_tokens", None)
        calls.append(
            {
                "purpose": purpose,
                "repair_reason": repair_reason,
                "status": status,
                "duration_ms": int(
                    round((time.perf_counter() - started) * 1000)
                ),
                "finish_reason": getattr(meta, "finish_reason", None),
                "usage": (
                    meta.usage
                    if meta is not None and isinstance(meta.usage, dict)
                    else None
                ),
                "ttft_ms": getattr(meta, "ttft_ms", None),
                "first_content_ms": getattr(meta, "first_content_ms", None),
                "server_timings": getattr(meta, "server_timings", None),
                "reasoning_present": getattr(meta, "reasoning_present", None),
                "reasoning_tokens": getattr(meta, "reasoning_tokens", None),
                "reasoning_budget_tokens": self._reasoning_budget_effective(
                    reasoning_budget_tokens, quick_turn
                ),
                "reasoning_deltas": getattr(meta, "reasoning_deltas", None),
                "content_deltas": getattr(meta, "content_deltas", None),
                "max_tokens": (
                    effective_max if isinstance(effective_max, int) else None
                ),
                "error_type": error_type,
            }
        )

    def _reasoning_budget_effective(self, reasoning_budget_tokens, quick_turn=False):
        """Presupuesto que el cliente resolverá/enviará, no cumplimiento del backend."""
        mode = str(getattr(self.llm, "thinking_mode", "") or "auto").strip().lower()
        provider = str(getattr(self.llm, "provider", "llama") or "llama").lower()
        if provider != "llama":
            return None
        if reasoning_budget_tokens is not None:
            return reasoning_budget_tokens
        if mode == "low":
            return LLM_REASONING_BUDGET_LOW_TOKENS
        if mode == "medium":
            return LLM_REASONING_BUDGET_MEDIUM_TOKENS
        if mode == "high":
            return LLM_REASONING_BUDGET_HIGH_TOKENS
        if mode == "auto" and quick_turn:
            return LLM_REASONING_BUDGET_LOW_TOKENS
        return None

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
        prompt_variant: domain_prompts.PromptVariant = "current",
        stream_llm=False,
        max_tokens_override: int | None = None,
        conversation_mode="normal",
        conversation_reason="",
        turn_kind="message",
        temporal=None,
    ):
        now = self.clock() if now is None else now
        session_mode = conversation_mode in ("spectator", "active", "proactive")
        from airi.domain.capabilities import TurnCapabilities

        capabilities = TurnCapabilities(date_active=isinstance(date_session, dict))
        schema = response_schema(capabilities, session_mode)
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
            # Turno breve: tono, relación, yo y memorias vigentes. Sin diario,
            # usuarios conocidos ni explicación larga de etiquetas; el mensaje
            # es corto, pero una pregunta puede depender de una preferencia.
            sections = [
                domain_prompts.temporal_context_section(
                    temporal, compact=True, mode=conversation_mode
                ),
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
                domain_prompts.memories_prompt_section(
                    _read_only_memories(state.memories, user.id)
                ),
            ]
        else:
            sections = [
                domain_prompts.temporal_context_section(
                    temporal, mode=conversation_mode
                ),
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
        mode_section = domain_prompts.conversation_mode_section(
            conversation_mode, conversation_reason
        )
        if mode_section:
            sections.append(mode_section)
        if extra_note:
            sections.append(
                f"\n\n=== NOTA INTERNA DEL SISTEMA ===\n{extra_note}\n"
            )
        from airi.domain.capabilities import TurnCapabilities

        capabilities = TurnCapabilities(date_active=isinstance(date_session, dict))
        date_section = domain_prompts.date_contract_section(capabilities)
        if date_section:
            sections.append(date_section)
        system_prompt = domain_prompts.build_system_prompt(
            web_context, sections, compact=quick, variant=prompt_variant
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
            now=now if temporal is not None else None,
            zone=temporal.zone if temporal is not None else None,
        )
        messages = [{"role": "system", "content": system_prompt}, *view]
        if conversation_mode == "proactive":
            messages.append(
                {
                    "role": "user",
                    "content": domain_prompts.PROACTIVE_TRIGGER_TEXT,
                }
            )
        request_tokens = (
            max_tokens_override
            if isinstance(max_tokens_override, int) and max_tokens_override > 0
            else LLM_SHORT_MAX_TOKENS if quick else None
        )
        calls: list[dict] = []
        repair_telemetry = {
            "review_on_topic": None,
            "review_issues": [],
            "review_ms": None,
            "repair_exhausted": False,
        }
        raw, meta = await self._chat(
            calls,
            "primary",
            messages,
            schema=schema,
            max_tokens=request_tokens,
            quick_turn=quick,
            stream_llm=stream_llm,
        )
        first_meta = meta
        stay_active = True
        if session_mode:
            output, stay_active, session_valid = parse_session_output(raw, delta_max=delta_max)
        else:
            session_valid = True
            output = parse_model_output(
                raw,
                delta_max=delta_max,
                allow_raw_fallback=False,
            )
        self._log_module("parsing", "activated", parse_ok=output.reply is not None)
        # Una sola política de parseo cubre truncamiento, reply vacío y JSON inválido.
        if (
            not session_mode
            or getattr(meta, "finish_reason", None) == "length"
            or not session_valid
        ):
            if getattr(meta, "finish_reason", None) == "length" and not (output.reply or "").strip():
                parse_symptom = "truncation"
            elif session_mode and not session_valid:
                parse_symptom = "invalid_json"
            elif not (output.reply or "").strip():
                parsed_raw = extract_json_object(raw) if isinstance(raw, str) else None
                parse_symptom = (
                    "empty"
                    if not isinstance(raw, str) or not raw.strip()
                    or (isinstance(parsed_raw, dict) and parsed_raw.get("reply") == "")
                    else "invalid_json"
                )
            else:
                parse_symptom = None
            if parse_symptom is not None:
                repaired = await self._repair(
                    calls,
                    "parse",
                    messages=messages,
                    schema=schema,
                    delta_max=delta_max,
                    max_tokens=request_tokens,
                    session_mode=session_mode,
                    symptom=parse_symptom,
                    stream_llm=stream_llm,
                )
                if repaired is not None and repaired.accepted:
                    raw, meta, output = repaired.raw, repaired.meta, repaired.output
                    if repaired.stay_active is not None:
                        stay_active = repaired.stay_active
                    self._log_module("parsing", "activated", parse_ok=True)
                else:
                    repair_telemetry["repair_exhausted"] = True

        # Los cierres interrogativos repetidos y las despedidas incoherentes
        # reciben parche determinista antes de la revisión semántica.
        previous_question = (
            not session_mode
            and not isinstance(date_session, dict)
            and domain_prompts.last_assistant_reply_ended_with_question(history)
        )
        if output.reply and previous_question and output.reply.rstrip().endswith("?"):
            trimmed = strip_trailing_questions(output.reply)
            if trimmed != output.reply:
                output = output._replace(reply=trimmed)

        deterministic_issues = quality_issues(
            output.reply or "", history,
            previous_closed_with_question=False,
        )
        if output.reply and disconnect_claim_problem(output.reply, bool(output.disconnect)):
            deterministic_issues.append(
                QualityIssue(
                    "disconnect", "incoherent", output.reply, "deterministic"
                )
            )

        if output.reply and self._should_review(
            in_date=isinstance(date_session, dict),
            quick=quick,
            kind=turn_kind,
            reply=output.reply,
            session_mode=session_mode,
        ):
            review_started = time.perf_counter()
            review = await self._review(
                calls, history=history, draft=output.reply, stream_llm=stream_llm
            )
            repair_telemetry["review_ms"] = int(
                round((time.perf_counter() - review_started) * 1000)
            )
            if review.valid:
                repair_telemetry["review_on_topic"] = review.on_topic
                repair_telemetry["review_issues"] = [
                    {"kind": issue.kind, "impact": issue.impact, "evidence": issue.evidence}
                    for issue in review.issues
                ]
            if calls and calls[-1].get("purpose") == "conversation_review":
                calls[-1]["review_on_topic"] = (
                    review.on_topic if review.valid else None
                )
                calls[-1]["review_issues"] = repair_telemetry["review_issues"]
                calls[-1]["review_ms"] = repair_telemetry["review_ms"]
            if review.valid:
                deterministic_issues = list(
                    merge_issues(deterministic_issues, review.issues)
                )

        repairable = tuple(
            issue for issue in deterministic_issues
            if issue.kind not in {"question_close"}
        )
        if output.reply and repairable:
            repaired = await self._repair(
                calls,
                "quality",
                messages=messages,
                schema=schema,
                delta_max=delta_max,
                max_tokens=request_tokens,
                session_mode=session_mode,
                issues=repairable,
                draft=raw if isinstance(raw, str) else "",
                stream_llm=stream_llm,
            )
            if repaired is not None and repaired.accepted:
                raw, meta, output = repaired.raw, repaired.meta, repaired.output
                if repaired.stay_active is not None:
                    stay_active = repaired.stay_active
            else:
                repair_telemetry["repair_exhausted"] = True

        # Última garantía determinista; la marcha se recorta solo si el residuo
        # es una frase publicable. El fallo de ese recorte se conserva como issue
        # para el siguiente bloque de agotamiento/telemetría.
        if output.reply and previous_question and output.reply.rstrip().endswith("?"):
            trimmed = strip_trailing_questions(output.reply)
            if trimmed != output.reply:
                output = output._replace(reply=trimmed)
        if output.reply and not output.disconnect:
            stripped, valid_strip = strip_leaving_claims(output.reply)
            if valid_strip and stripped != output.reply:
                output = output._replace(reply=stripped)
            elif not valid_strip:
                repair_telemetry["repair_exhausted"] = True

        if stream_llm:
            # TTFT describe la primera solicitud, aunque haya una regeneración.
            meta.ttft_ms = first_meta.ttft_ms
            meta.first_content_ms = first_meta.first_content_ms
            meta.server_timings = first_meta.server_timings
            meta.reasoning_present = first_meta.reasoning_present
            meta.reasoning_tokens = first_meta.reasoning_tokens
        if (not session_mode) and not output.reply:
            return (
                system_prompt,
                raw if isinstance(raw, str) else None,
                meta,
                ModelOutput(
                    None, "none", "none", "none", 0,
                    "continue", "none", "none",
                ),
                True,
                calls,
                repair_telemetry,
            )
        # stay_active solo es significativo en modo sesión; en modo normal se
        # conserva el valor por defecto.
        if not session_mode:
            stay_active = True
        if isinstance(output.reply, str):
            limited = limit_narrative_actions(output.reply)
            if limited != output.reply:
                output = output._replace(reply=limited)
        return (
            system_prompt,
            raw if isinstance(raw, str) else None,
            meta,
            output,
            stay_active,
            calls,
            repair_telemetry,
        )

    def _should_review(
        self, *, in_date, quick, kind, reply, session_mode=False
    ) -> bool:
        """Decide si el texto es conversacional y merece revisión semántica."""
        if not self.conversation_review_enabled or not (reply or "").strip():
            return False
        if quick or in_date:
            return False
        if kind in {"date_action", "scene_select", "command"}:
            return False
        # spectator/active/proactive son interacciones conversacionales válidas;
        # `session_mode` no las excluye, pero el silencio sí se excluyó arriba.
        return True

    async def _review(self, calls, *, history, draft, stream_llm=False):
        """Juez corto y sin personalidad; cualquier fallo abre el paso."""
        if not isinstance(draft, str) or not draft.strip():
            return ReviewResult(valid=False)
        lines = []
        for msg in (history or [])[-10:]:
            if not isinstance(msg, Mapping):
                continue
            role = msg.get("role")
            if role not in {"user", "assistant"}:
                continue
            author = msg.get("author_name")
            if not isinstance(author, str) or not author.strip():
                author = "Usuario" if role == "user" else "Airi"
            content = (
                msg.get("content", "")
                if role == "user"
                else assistant_reply_text(msg.get("content", ""))
            )
            if not isinstance(content, str) or not content.strip():
                continue
            content = " ".join(content.split())[:350]
            lines.append(f"{author} ({role}): {content}")
        transcript = "\n".join(lines) or "(sin historial previo)"
        user_prompt = (
            "HILO RECIENTE:\n" + transcript + "\n\nBORRADOR:\n" + draft[:700]
        )
        try:
            raw, _meta = await self._chat(
                calls,
                "conversation_review",
                [
                    {"role": "system", "content": CONVERSATION_REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                schema=CONVERSATION_REVIEW_SCHEMA,
                max_tokens=256,
                stream_llm=stream_llm,
            )
            return parse_review(raw, draft=draft)
        except Exception:
            log.warning("La revisión semántica falló; se publica el borrador", exc_info=True)
            return ReviewResult(valid=False)

    async def _repair(
        self, calls, policy, *, messages, schema, delta_max, max_tokens,
        session_mode=False, symptom=None, issues=(), draft=None, stream_llm=False,
    ):
        """Ejecuta una política de reparación una vez y valida su resultado."""
        if policy == "parse":
            note = PARSE_REPAIR_PROMPTS.get(symptom)
            if note is None:
                raise ValueError(f"Síntoma de parseo desconocido: {symptom}")
            if session_mode:
                note += " Incluye también `stay_active` como booleano."
            repair_messages = [*messages, {"role": "user", "content": note}]
            reason = symptom
            purpose = "parse_repair"
        elif policy == "quality":
            if not isinstance(draft, str) or not issues:
                raise ValueError("quality_repair requiere borrador e issues")
            evidence_spans = [issue.evidence for issue in issues if issue.evidence]
            lines = [
                f"- {issue.kind} ({issue.impact}): evidencia literal {issue.evidence!r}"
                for issue in issues
            ]
            note = QUALITY_REPAIR_PROMPT + "\n".join(lines)
            repair_messages = [
                *messages,
                {"role": "assistant", "content": draft},
                {"role": "user", "content": note},
            ]
            reason = "+".join(issue.kind for issue in issues)
            purpose = "quality_repair"
        else:
            raise ValueError(f"Política de reparación desconocida: {policy}")

        try:
            raw, meta = await self._chat(
                calls, purpose, repair_messages, schema=schema,
                max_tokens=max_tokens, stream_llm=stream_llm,
                repair_reason=reason,
            )
            if session_mode:
                fixed, stay_active, valid = parse_session_output(raw, delta_max=delta_max)
                if not valid:
                    return None
            else:
                fixed = parse_model_output(
                    raw, delta_max=delta_max,
                    allow_raw_fallback=getattr(meta, "finish_reason", None) != "length",
                )
                stay_active = None
            if not isinstance(fixed.reply, str) or not fixed.reply.strip():
                return None
            if policy == "quality":
                old_reply = parse_model_output(draft, delta_max=delta_max).reply or ""
                new_reply = fixed.reply
                old_tokens = len(old_reply.split())
                if len(new_reply.split()) < old_tokens * 0.5:
                    return None
                if old_tokens >= 25 and token_overlap(
                    old_reply, new_reply, ignored=evidence_spans
                ) < 0.60:
                    return None
            return RepairOutcome(
                raw=raw, meta=meta, output=fixed, stay_active=stay_active,
                accepted=True, reason=reason,
            )
        except Exception:
            if stream_llm:
                raise
            log.warning("La política %s falló (%s)", purpose, reason, exc_info=True)
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

    def _register_user(self, who, now):
        # Los usuarios sintéticos (turnos proactivos, mensajes pendientes) no
        # son personas reales: no deben registrarse ni disparar "Nuevo encuentro".
        if getattr(who, "bot", False) or getattr(who, "id", None) in (None, 0):
            return False
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
        return is_new

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
