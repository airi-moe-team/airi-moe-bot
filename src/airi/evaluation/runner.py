"""Runner mínimo de escenarios narrativos sobre `ConversationService`.

Sirve para ejecutar una conversación multi-turno con cualquier LLM (real o
falso) y producir los registros que consume `evaluate_records`. No levanta
Discord ni persiste: recibe un servicio ya construido y un estado sembrado.
"""

from __future__ import annotations

from airi.domain.relationship_claims import looks_like_romantic_question
from airi.services.conversation import ConversationService, TurnContext


async def run_scenario(
    scenario,
    service: ConversationService,
    user,
    *,
    now: float,
    channel_id: int = 0,
    turn_prefix: str = "eval",
) -> list[dict]:
    """Ejecuta los turnos de un escenario y devuelve registros evaluables."""
    records: list[dict] = []
    for index, text in enumerate(scenario.turns, start=1):
        ctx = TurnContext(
            channel_id=channel_id,
            turn_key=f"{turn_prefix}:{scenario.id}:{index}",
            now=now + index,
        )
        draft = await service.generate_turn(user, [(user, text)], ctx)
        result = service.apply_turn(draft)
        output = draft.output
        update = result.romantic_update_action
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
            }
        )
    return records
