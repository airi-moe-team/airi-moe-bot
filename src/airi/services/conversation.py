"""Servicio de conversación: un turno completo sin Discord ni HTTP directo."""

from __future__ import annotations

import copy
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable

from airi.domain import memories as domain_memories
from airi.domain import prompts as domain_prompts
from airi.domain import users as domain_users
from airi.domain.affinity import (
    AFFINITY_DELTA_MAX,
    affinity_level,
    entry_points,
    level_rank,
)
from airi.domain.budget import estimate_tokens, fit_history
from airi.domain.constants import (
    DATE_HISTORY_MAX,
    DIARY_REFLECTION_MIN_INTERVAL,
    LLM_CONTEXT_TOKENS,
    LLM_OUTPUT_TOKENS,
    MAX_HISTORY_MESSAGES,
    SEARCH_QUERY_MAX_TOKENS,
)
from airi.domain.diary import add_diary_entry, new_diary_entry
from airi.domain.grounding import reply_seems_grounded
from airi.domain.llm_output import (
    RESPONSE_SCHEMA,
    ModelOutput,
    assistant_history_content,
    parse_model_output,
)
from airi.domain.prompts import SEARCH_QUERY_PROMPT
from airi.domain.text_filters import (
    clean_reply,
    remove_repeated_previous_reply,
    strip_repetition_loop,
)
from airi.domain.web import needs_web_search
from airi.logging_setup import (
    get_logger,
    reset_correlation_id,
    set_correlation_id,
)
from airi.observability.trace import TurnEvent
from airi.observability.trace_store import TraceStore
from airi.ports.llm import LLMMeta
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

MEMORY_SAVED_NOTICE = "Airi recordará este evento"


@dataclass
class TurnContext:
    channel_id: int | str = 0
    allow_web: bool = True
    now: float | None = None  # None → reloj del servicio (testeable)
    correlation_id: str | None = None  # None → se genera uno por turno
    kind: str = "message"  # message | gift | scene_select | date_question_result | command
    raw_input: str | None = None  # None → se une de `messages`
    extra_note: str | None = None  # nota interna extra para el system prompt
    suppress_affinity: bool = False  # ignora el delta que devuelva el modelo
    on_trace: Callable[[TurnEvent], None] | None = None  # hook post-turno


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
    history: list = field(default_factory=list)
    skipped: bool = False
    trace: TurnEvent | None = None


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
    ):
        self.llm = llm
        self.state = state
        self.search = search
        self.gifs = gifs
        self.notifier = notifier
        self.clock = clock
        self.max_history = max_history
        self.date_delta_max = date_delta_max
        # Almacén de eventos: por defecto el del AppState.
        self.traces = traces if traces is not None else getattr(state, "traces", None)

    async def run_turn(self, user, messages, ctx: TurnContext) -> TurnResult:
        """Procesa un turno (lista de `(user_obj, texto)` ya unida)."""
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

        try:
            log.info("turno user=%s", uid)

            # Snapshots ANTES de cualquier mutación (replay fiel).
            ev.state_snapshot_affinity = dict(self.state.affinity.get(str(uid), {}))
            # Deep-copy: el "self" y otros sub-dicts se mutan en el sitio; sin
            # copia profunda el snapshot del replay se contaminaría.
            ev.state_snapshot_world = copy.deepcopy(self.state.world)
            ev.state_snapshot_memories = list(self.state.memories.get(str(uid), []))
            ev.state_snapshot_diary = list(self.state.diary[-20:])
            _sess0 = self.state.dates.get(str(uid))
            ev.state_snapshot_date = dict(_sess0) if isinstance(_sess0, dict) else None
            ev.in_date = isinstance(_sess0, dict)
            ev.date_state = _sess0.get("state") if isinstance(_sess0, dict) else None
            ev.date_turns_before = (
                int(_sess0.get("turns", 0) or 0) if isinstance(_sess0, dict) else 0
            )
            ev.affinity_before = entry_points(self.state.affinity_entry(uid))

            for who, _part in messages:
                self._register_user(who, now)

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
                    "content": f"{who.display_name}: {part}",
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
            t0 = _time.perf_counter()
            system_prompt, raw_llm, meta, output = await self._generate(
                history, web_context, user, date_session, delta_max,
                extra_note=ctx.extra_note, event=ev,
            )
            # Turnos internos (p. ej. la reacción a la pregunta): el motor ya
            # aplicó el swing, así que se ignora lo que devuelva el modelo.
            if ctx.suppress_affinity:
                output = output._replace(affinity_delta=0, affinity_event="none")
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
            }
            answer = remove_repeated_previous_reply(output.reply, history)
            answer = strip_repetition_loop(answer)
            if not answer:
                log.info("Se omitió una respuesta duplicada sin contenido nuevo.")
                ev.skipped = True
                ev.timings_ms = timings
                return TurnResult(
                    skipped=True,
                    in_date=in_date,
                    web_context=web_context,
                    history=history,
                    trace=ev,
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
                    None,
                )
                grounded = False
            ev.grounded = grounded

            # Motor de afinidad juzgado por la IA (con decay por inactividad).
            # El tope ya se aplicó al parsear; aquí se reusa para persistir.
            entry = self.state.affinity_entry(uid)
            level_before = affinity_level(entry_points(entry))[0]
            ev.affinity_delta_requested = output.affinity_delta
            applied = self.state.apply_affinity(
                uid, output.affinity_delta, now=now, delta_max=delta_max
            )
            points_now = self.state.entry_points(uid)
            level_after = affinity_level(points_now)[0]
            leveled_up = level_rank(level_after) > level_rank(level_before)
            if leveled_up:
                self.state.log_diary_event(
                    "level",
                    user,
                    f"Empiezo a sentir algo más por {self.state.display_name(uid)}; "
                    f"nuestra relación ha subido a «{level_after}».",
                )
            log.info(
                "afinidad %+d (aplicado %+d) total=%d (%s→%s)",
                output.affinity_delta, applied, points_now,
                level_before, level_after,
            )

            # El diario solo se escribe en turnos-hito (subida de nivel aquí, o
            # fin de cita fuera, en DateService).
            diary_saved = False
            if leveled_up and output.diary.lower() != "none":
                diary_saved = self._add_diary_reflection(uid, output.diary, now)

            memory_saved = domain_memories.process_memory_action(
                self.state.memories, uid, output.memory, now=now
            )
            if memory_saved:
                self.state.save_memories()
                if self.notifier is not None:
                    try:
                        await self.notifier.send(MEMORY_SAVED_NOTICE)
                    except Exception:
                        log.warning("No se pudo enviar el aviso de memoria guardada")

            # Identidad: Airi puede reescribir UNA parte de su "yo". Los
            # guardarraíles (allowlist, clamps, motivo, rate-limit) viven en
            # `airi.domain.self_model.apply_self_update`.
            self_changed = False
            self_entry = None
            if output.self_update:
                self_entry = self.state.apply_self_change(
                    output.self_update,
                    now=now,
                    user_id=uid,
                    source="date" if in_date else "message",
                )
                if self_entry is not None:
                    self_changed = True
                    log.info(
                        "Airi cambia de identidad: %s %s %s→%s (%s)",
                        self_entry["key"], self_entry["op"],
                        self_entry["from"], self_entry["to"], self_entry["reason"],
                    )
                else:
                    log.info(
                        "Cambio de identidad rechazado: %s", output.self_update
                    )

            history.append({
                "role": "assistant",
                "content": assistant_history_content(answer, output),
            })
            if in_date and isinstance(date_session, dict):
                date_session["history"] = history[-DATE_HISTORY_MAX:]
                self.state.save_dates()
            else:
                self.state.histories[ctx.channel_id] = history[-self.max_history:]

            gif_bytes = None
            if output.gif != "none" and self.gifs is not None:
                gif_bytes = await self.gifs.fetch(output.gif)

            ev.final_reply = answer
            ev.gif = output.gif
            ev.gif_sent = gif_bytes is not None
            ev.gif_fetched = gif_bytes is not None
            ev.memory_saved = output.memory if memory_saved else None
            ev.diary_saved = output.diary if diary_saved else None
            ev.affinity_after = points_now
            ev.affinity_applied = applied
            ev.affinity_event = output.affinity_event
            ev.self_changed = self_changed
            ev.self_update_action = self_entry
            ev.level_before = level_before
            ev.level_after = level_after
            ev.leveled_up = leveled_up
            ev.date_decision = output.date_decision
            ev.date_turns_after = (
                int(date_session.get("turns", 0) or 0)
                if in_date and isinstance(date_session, dict) else 0
            )
            ev.timings_ms = timings
            result = TurnResult(
                reply=answer,
                gif=output.gif,
                gif_bytes=gif_bytes,
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
                grounded=grounded,
                web_context=web_context,
                memory_saved=memory_saved,
                diary_saved=diary_saved,
                self_changed=self_changed,
                self_update_action=self_entry,
                history=history,
                trace=ev,
            )
            log.info(
                "turno ok reply=%d chars gif=%s grounded=%s",
                len(answer), output.gif, grounded,
            )
            return result
        except Exception as exc:
            ev.errors.append({
                "type": type(exc).__name__,
                "msg": str(exc),
                "tb": traceback.format_exc(),
            })
            ev.error = str(exc)
            raise
        finally:
            ev.finish()
            if self.traces is not None:
                await self.traces.save(ev)
            self._emit_trace(ctx, ev)
            reset_correlation_id(token)

    # ------------------------------------------------------------------

    async def _generate(
        self, history, web_context, user, date_session, delta_max, extra_note=None,
        event=None,
    ):
        now = self.clock()
        state = self.state
        points = state.entry_points(user.id)
        sections = [
            domain_prompts.affinity_prompt_section(
                points, affinity_level(points)[0], user.display_name
            ),
            domain_prompts.relationship_status_section(
                state.world,
                state.users,
                user_id=user.id,
                display_name=user.display_name,
                now=now,
            ),
            domain_prompts.preferences_prompt_section(state.world),
            domain_prompts.self_model_prompt_section(state.self_model()),
            domain_prompts.date_context_section(
                date_session if isinstance(date_session, dict) else None
            ),
            domain_prompts.memories_prompt_section(state.user_memories(user.id)),
            domain_prompts.known_users_prompt_section(
                state.users,
                state.diary,
                state.world,
                user_id=user.id,
                display_name=user.display_name,
            ),
            domain_prompts.diary_prompt_section(state.diary, user.id, now),
        ]
        if extra_note:
            sections.append(f"\n\n=== NOTA INTERNA DEL SISTEMA ===\n{extra_note}\n")
        system_prompt = domain_prompts.build_system_prompt(web_context, sections)
        # Presupuesto de contexto: recorta el historial (nunca el system)
        # para que prompt + salida quepan en el techo del servidor.
        history, history_trimmed = fit_history(
            system_prompt,
            history,
            output_tokens=LLM_OUTPUT_TOKENS,
            context_tokens=LLM_CONTEXT_TOKENS,
        )
        if history_trimmed:
            log.warning(
                "Historial recortado por techo de contexto (%d tokens)",
                LLM_CONTEXT_TOKENS,
            )
        messages = [{"role": "system", "content": system_prompt}, *history]
        if hasattr(self.llm, "chat_with_meta"):
            try:
                # Salida estricta: la gramática del servidor garantiza JSON
                # aunque el modelo quiera responder en texto plano.
                raw, meta = await self.llm.chat_with_meta(
                    messages, schema=RESPONSE_SCHEMA, strict_schema=True,
                    max_tokens=LLM_OUTPUT_TOKENS, disable_thinking=True,
                )
            except Exception:
                log.warning(
                    "La salida estricta no está soportada por el servidor; "
                    "se reintenta en modo json_object.",
                    exc_info=True,
                )
                raw, meta = await self.llm.chat_with_meta(
                    messages, schema=RESPONSE_SCHEMA,
                    max_tokens=LLM_OUTPUT_TOKENS, disable_thinking=True,
                )
        else:
            raw = await self.llm.chat(
                messages, schema=RESPONSE_SCHEMA,
                max_tokens=LLM_OUTPUT_TOKENS, disable_thinking=True,
            )
            meta = LLMMeta()
        output = parse_model_output(raw, delta_max=delta_max)
        if event is not None:
            event.prompt_tokens_est = estimate_tokens(system_prompt) + sum(
                estimate_tokens(m.get("content", "") if isinstance(m, dict) else m)
                for m in history
            )
            event.history_trimmed = bool(history_trimmed)
            event.output_truncated = (meta.finish_reason == "length")
            if event.output_truncated:
                log.warning(
                    "El modelo agotó max_tokens (%d): posible generación desbocada",
                    LLM_OUTPUT_TOKENS,
                )
        if not output.reply:
            return (
                system_prompt,
                raw if isinstance(raw, str) else None,
                meta,
                ModelOutput(
                    None, "none", "none", "none", 0,
                    "continue", "none", "none", None,
                ),
            )
        return system_prompt, raw if isinstance(raw, str) else None, meta, output

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



