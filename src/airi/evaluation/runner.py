"""Runner mínimo de escenarios narrativos sobre `ConversationService`.

Sirve para ejecutar una conversación multi-turno con cualquier LLM (real o
falso) y producir los registros que consume `evaluate_records`. No levanta
Discord ni persiste: recibe un servicio ya construido y un estado sembrado.
"""

from __future__ import annotations

import copy

from airi.domain.relationship_claims import looks_like_romantic_question
from airi.services.conversation import ConversationService, TurnContext

_SAFE_LLM_CALL_FIELDS = (
    "purpose",
    "status",
    "duration_ms",
    "finish_reason",
    "usage",
    "ttft_ms",
    "first_content_ms",
    "server_timings",
    "reasoning_present",
    "reasoning_tokens",
    "reasoning_deltas",
    "content_deltas",
    "max_tokens",
    "thinking_requested_off",
    "thinking_effective",
    "error_type",
)


def _safe_llm_calls(trace) -> list[dict]:
    calls = getattr(trace, "llm_calls", None) or []
    return [
        {key: call[key] for key in _SAFE_LLM_CALL_FIELDS if key in call}
        for call in calls
        if isinstance(call, dict)
    ]


async def run_scenario(
    scenario,
    service: ConversationService,
    user,
    *,
    now: float,
    channel_id: int = 0,
    turn_prefix: str = "eval",
    prompt_variant: str = "current",
) -> list[dict]:
    """Ejecuta los turnos de un escenario y devuelve registros evaluables."""
    records: list[dict] = []
    for index, text in enumerate(scenario.turns, start=1):
        ctx = TurnContext(
            channel_id=channel_id,
            turn_key=f"{turn_prefix}:{scenario.id}:{index}",
            now=(scenario.now if getattr(scenario, "now", None) is not None else now) + index,
            kind=("proactive" if getattr(scenario, "conversation_mode", "normal") == "proactive" else "message"),
            conversation_mode=getattr(scenario, "conversation_mode", "normal"),
            system_prompt_variant=prompt_variant,
        )
        draft = await service.generate_turn(user, [(user, text)], ctx)
        result = service.apply_turn(draft)
        output = draft.output
        trace = draft.trace
        update = result.romantic_update_action
        memories = getattr(service.state, "memories", {}) if service.state else {}
        user_id = getattr(user, "id", None)
        memories_after = (
            copy.deepcopy(list(memories.get(str(user_id), [])))
            if user_id is not None
            else []
        )
        records.append(
            {
                "scenario": scenario.id,
                "category": scenario.category,
                "turn": index,
                "user": text,
                "reply": result.reply or "",
                "romantic_question": bool(output.date_question)
                or looks_like_romantic_question(result.reply or ""),
                "stage_before": result.romantic_stage_before,
                "stage_after": result.romantic_stage_after,
                "romantic_update": update.get("to") if update else None,
                "evidence_refs": list(update.get("evidence_refs") or [])
                if update
                else [],
                "partner_confirmed": result.partner_confirmed,
                "proposal_pending": result.proposal_pending,
                # Contrato de estado y trazabilidad para la evaluación de
                # naturalidad (R7-R12). Son campos aditivos: los consumidores
                # narrativos existentes los ignoran.
                "conversation_mode": ctx.conversation_mode,
                "time_context": dict(getattr(trace, "time_context", {}) or {}),
                "disconnect": getattr(output, "disconnect", None),
                "stay_active": bool(getattr(result, "stay_active", True)),
                "parse_ok": bool(getattr(trace, "parse_ok", True)),
                "parse_warnings": list(getattr(trace, "parse_warnings", []) or []),
                "finish_reason": getattr(trace, "llm_finish_reason", None),
                "raw_llm": getattr(trace, "raw_llm", None),
                "prompt_system": getattr(trace, "prompt_system", ""),
                "llm_usage": getattr(trace, "llm_usage", None),
                "llm_calls": _safe_llm_calls(trace),
                "llm_latency_ms": int(getattr(trace, "llm_latency_ms", 0) or 0),
                "total_latency_ms": int(getattr(trace, "total_latency_ms", 0) or 0),
                "memories_after": memories_after,
            }
        )
    return records
