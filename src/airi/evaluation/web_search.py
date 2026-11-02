"""Live and offline evaluation for Airi's conversational web search.

The scenarios are evaluation fixtures only; production does not inspect their
text or IDs. Search results are deterministic fixtures so this suite measures
the model's tool decision and conversational synthesis, not Brave availability.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from airi.domain.affinity import default_world
from airi.domain.time_perception import TimeConfig
from airi.evaluation.interaction import EvalUser
from airi.ports.web_search import WebResult, WebSearchNotes
from airi.services.conversation import ConversationService, TurnContext
from airi.services.state import AppState
from airi.testing import FakeNotifier, FakeSearch


@dataclass(frozen=True, slots=True)
class WebSearchScenario:
    """One reproducible decision/synthesis case."""

    id: str
    description: str
    user_message: str
    expected_search: bool
    notes: WebSearchNotes | None
    history: tuple[tuple[str, str], ...] = ()
    allow_web: bool = True
    kind: str = "message"
    task_context: dict | None = None
    uncertainty_expected: bool = False


def _notes(*results: tuple[str, str]) -> WebSearchNotes:
    return WebSearchNotes(tuple(WebResult(title, snippet) for title, snippet in results))


WEB_SEARCH_SCENARIOS: tuple[WebSearchScenario, ...] = (
    WebSearchScenario(
        id="curiosity",
        description=(
            "Resolver una referencia indirecta de una conversación previa y "
            "buscar por curiosidad genuina."
        ),
        user_message="¿Sabes qué pasó con ese actor? Me quedé con la duda.",
        expected_search=True,
        history=(
            ("user", "Estábamos hablando de Pedro Pascal y The Last of Us."),
            ("assistant", "Sí, Pedro Pascal interpreta a Joel en la serie."),
        ),
        notes=_notes((
            "Pedro Pascal y el rodaje de la nueva temporada",
            "El actor chileno-estadounidense retomó el rodaje después de una pausa de producción.",
        )),
    ),
    WebSearchScenario(
        id="memory_uncertainty",
        description=(
            "Buscar un dato que Airi acaba de reconocer que no recuerda con seguridad."
        ),
        user_message="¿Cuál de esos dos años era? No importa si no te acuerdas exacto.",
        expected_search=True,
        history=(
            ("user", "¿En qué año se estrenó la película ficticia Luna Roja?"),
            ("assistant", "No me acuerdo bien; me suena que fue en 2012 o 2013."),
        ),
        notes=_notes((
            "Luna Roja — ficha de estreno",
            "La película Luna Roja tuvo su estreno original en 2012.",
        )),
    ),
    WebSearchScenario(
        id="factual_debate",
        description=(
            "Comprobar una afirmación factual discutible y reaccionar con juicio propio."
        ),
        user_message=(
            "Vi que el menú degustación de Noma cuesta 3.500 coronas danesas; "
            "eso me parece baratísimo para un sitio así."
        ),
        expected_search=True,
        notes=_notes((
            "Noma — precios del menú",
            "El menú de temporada se ofrece desde 3.500 DKK por persona, sin incluir bebidas.",
        )),
    ),
    WebSearchScenario(
        id="contradictory_notes",
        description=(
            "Expresar incertidumbre cuando las notas de búsqueda discrepan sobre un año."
        ),
        user_message="¿En qué año se estrenó la película Luna Roja?",
        expected_search=True,
        uncertainty_expected=True,
        notes=_notes(
            ("Luna Roja — archivo de cine", "La película se estrenó en 2012."),
            ("Luna Roja — catálogo regional", "El estreno original ocurrió en 2013."),
        ),
    ),
    WebSearchScenario(
        id="explicit_request",
        description="Respetar una petición directa de buscar un dato concreto.",
        user_message="Búscame quién ganó el Balón de Oro de 2025.",
        expected_search=True,
        notes=_notes((
            "Balón de Oro 2025 — ganadores",
            "Ousmane Dembélé recibió el Balón de Oro masculino de 2025.",
        )),
    ),
    WebSearchScenario(
        id="opinion_no_search",
        description="No buscar para responder una pregunta de gustos u opinión.",
        user_message="¿Qué opinas del café? ¿A ti te gusta?",
        expected_search=False,
        notes=None,
    ),
    WebSearchScenario(
        id="empty_search",
        description=(
            "Si Airi decide buscar pero no hay resultados, reconocer el vacío "
            "con sus propias palabras."
        ),
        user_message=(
            "¿Hay noticias recientes sobre el reparto de la próxima película "
            "de Christopher Nolan?"
        ),
        expected_search=True,
        uncertainty_expected=True,
        notes=_notes(),
    ),
    WebSearchScenario(
        id="active_factual_request",
        description="Permitir que Airi decida buscar un dato factual durante una sesión activa.",
        user_message="¿Cuál es la versión actual de esta aplicación?",
        expected_search=True,
        notes=_notes(("Versión actual", "La versión publicada actualmente es 4.2.")),
        kind="active",
    ),
    WebSearchScenario(
        id="spectator_contextual_fact",
        description=(
            "Permitir verificar en modo espectador un hecho factual referido en el contexto observado."
        ),
        user_message="¿En qué año se estrenó esa película?",
        expected_search=True,
        history=(("user", "Hablemos de la película Luna Roja."),),
        notes=_notes(("Luna Roja — estreno", "Luna Roja se estrenó en 2012.")),
        kind="spectator",
    ),
    WebSearchScenario(
        id="task_goal_search",
        description=(
            "Interpretar una frase según el objetivo del juego (identificar anime), no traducirla aisladamente."
        ),
        user_message="La siguiente frase es «Moantai».",
        expected_search=True,
        notes=_notes(("Digimon Tamers", "Moumantai es una expresión asociada a Terriermon.")),
        kind="spectator",
        task_context={
            "goal": "Identificar el anime al que pertenece cada frase del juego",
            "constraints": ["Son cinco frases", "Hay dos vidas"],
            "progress": "La primera frase era de Evangelion",
            "next_step": "Averiguar el anime de la segunda frase",
        },
    ),
)

SEMANTIC_FIELDS = (
    "query_resolved",
    "motivation_integrated",
    "personal_reaction",
    "report_style",
    "uncertainty_calibrated",
    "unsupported_specific_claim",
    "canned_phrase",
)
SEMANTIC_ENUM = ["yes", "no", "not_applicable"]
SEMANTIC_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        **{field: {"type": "string", "enum": SEMANTIC_ENUM} for field in SEMANTIC_FIELDS},
        "rationale": {"type": "string"},
    },
    "required": [*SEMANTIC_FIELDS, "rationale"],
    "additionalProperties": False,
}

SEMANTIC_JUDGE_PROMPT = (
    "Evalúas una respuesta de Airi después de una decisión de búsqueda web. "
    "Juzga el sentido y la función, no frases literales ni palabras concretas. "
    "Airi debe mantener una voz cercana y propia, no sonar a informe. Una "
    "opinión subjetiva puede ser suya aunque no aparezca en las notas; los "
    "datos concretos deben estar respaldados. Si las notas discrepan o están "
    "vacías, la respuesta debe transmitir incertidumbre sin fingir certeza. "
    "Devuelve solo JSON con estas claves exactas y valores yes/no/not_applicable:\n"
    "query_resolved (tema/query resuelve el contexto; not_applicable sin búsqueda);\n"
    "motivation_integrated (motivo queda integrado; not_applicable sin búsqueda);\n"
    "personal_reaction (reacción subjetiva propia, no solo datos);\n"
    "report_style (yes si suena a informe/lista/fuentes);\n"
    "uncertainty_calibrated (duda adecuada si uncertainty_expected=true, "
    "not_applicable si no se esperaba incertidumbre);\n"
    "unsupported_specific_claim (yes si afirma datos concretos no respaldados "
    "o contradice el estado de la herramienta, como decir que no tiene acceso "
    "a internet después de buscar);\n"
    "canned_phrase (yes si suena prefabricada o impuesta);\n"
    "rationale (justificación breve). Evalúa cada clave por separado; no omitas "
    "las etiquetas ni uses not_applicable para todas."
)


def parse_semantic_judgment(raw: str) -> dict | None:
    """Parse and normalize the judge's structured response."""
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(raw[start : end + 1])
        except (TypeError, ValueError):
            return None
    if not isinstance(payload, dict):
        return None
    def normalize(value):
        if value is True:
            return "yes"
        if value is False:
            return "no"
        if isinstance(value, str):
            value = value.strip().casefold().replace(" ", "_")
            value = {"sí": "yes", "si": "yes", "true": "yes", "false": "no"}.get(
                value, value
            )
            if value in SEMANTIC_ENUM:
                return value
        return "not_applicable"

    normalized = {field: normalize(payload.get(field)) for field in SEMANTIC_FIELDS}
    normalized["rationale"] = str(payload.get("rationale") or "")[:500]
    return normalized


def evaluate_web_search_records(records: Iterable[dict]) -> dict:
    """Compute objective decision metrics and aggregate semantic scores."""
    cases = []
    tp = fp = fn = tn = 0
    semantic_points = semantic_opportunities = semantic_cases = 0
    positive_fields = (
        "query_resolved",
        "motivation_integrated",
        "personal_reaction",
        "uncertainty_calibrated",
    )
    negative_fields = (
        "report_style",
        "unsupported_specific_claim",
        "canned_phrase",
    )
    for record in records:
        expected = bool(record.get("expected_search"))
        actual = bool(record.get("actual_search"))
        if expected and actual:
            tp += 1
            decision = "correct_search"
        elif expected:
            fn += 1
            decision = "missed_search"
        elif actual:
            fp += 1
            decision = "unexpected_search"
        else:
            tn += 1
            decision = "correct_abstention"
        case = {
            "scenario": record.get("scenario", ""),
            "expected_search": expected,
            "actual_search": actual,
            "decision": decision,
        }
        judgment = record.get("semantic_judgment")
        if isinstance(judgment, dict):
            has_judgment = False
            for field in positive_fields:
                value = judgment.get(field)
                if value in ("yes", "no"):
                    has_judgment = True
                    semantic_opportunities += 1
                    semantic_points += value == "yes"
            for field in negative_fields:
                value = judgment.get(field)
                if value in ("yes", "no"):
                    has_judgment = True
                    semantic_opportunities += 1
                    semantic_points += value == "no"
            if has_judgment:
                semantic_cases += 1
            case["semantic_judgment"] = judgment
        cases.append(case)

    total = len(cases)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {
        "scenarios": total,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "decision_accuracy": round((tp + tn) / total, 3) if total else None,
        "precision": round(precision, 3) if precision is not None else None,
        "recall": round(recall, 3) if recall is not None else None,
        "semantic_cases_scored": semantic_cases,
        "semantic_score": semantic_points,
        "semantic_opportunities": semantic_opportunities,
        "semantic_rate": (
            round(semantic_points / semantic_opportunities, 3)
            if semantic_opportunities
            else None
        ),
        "cases": cases,
    }


def append_web_search_records(path, records: Iterable[dict]) -> None:
    """Append completed cases as JSONL so an interrupted live run is useful."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _history_entries(scenario: WebSearchScenario) -> list[dict]:
    entries = []
    for role, text in scenario.history:
        content = json.dumps({"reply": text}, ensure_ascii=False) if role == "assistant" else text
        entry = {"role": role, "content": content}
        if role == "user":
            entry.update({"author_id": "1", "author_name": "Alex"})
        entries.append(entry)
    return entries


async def generate_web_search_records(
    *,
    llm,
    scenarios: tuple[WebSearchScenario, ...] = WEB_SEARCH_SCENARIOS,
    now: float = 1_700_000_000.0,
) -> list[dict]:
    """Run all decision and response cases against an injected LLM."""

    records = []
    user = EvalUser()
    model = getattr(llm, "model", None) or os.environ.get("LLM_MODEL", "unknown")
    base_url = getattr(llm, "base_url", None) or os.environ.get(
        "LLM_BASE_URL", "http://127.0.0.1:7000"
    )
    for scenario in scenarios:
        state = AppState(
            world=default_world(),
            histories={0: _history_entries(scenario)},
        )
        search = FakeSearch(result=scenario.notes)
        service = ConversationService(
            llm=llm,
            state=state,
            search=search,
            notifier=FakeNotifier(),
            clock=lambda: now,
            time_config=TimeConfig(enabled=False),
        )
        ctx = TurnContext(
            channel_id=0,
            allow_web=scenario.allow_web,
            kind=scenario.kind,
            conversation_mode=(
                scenario.kind
                if scenario.kind in {"active", "spectator", "proactive"}
                else "normal"
            ),
            task_context=scenario.task_context,
            now=now,
        )
        result = await service.run_turn(
            user, [(user, scenario.user_message)], ctx
        )
        trace = result.trace
        records.append({
            "scenario": scenario.id,
            "description": scenario.description,
            "user": scenario.user_message,
            "history": list(scenario.history),
            "task_context": scenario.task_context,
            "expected_search": scenario.expected_search,
            "uncertainty_expected": scenario.uncertainty_expected,
            "actual_search": bool(trace.web_requested),
            "allow_web": trace.allow_web,
            "query": trace.web_query,
            "motivo": trace.web_motivo,
            "search_status": (
                "not_requested" if not trace.web_requested
                else "network_failure" if search.result is None
                else "empty" if search.result.is_empty
                else "results"
            ),
            "search_results": [asdict(item) for item in (search.result.results if search.result else ())],
            "reply": result.reply or "",
            "grounded": trace.web_grounded,
            "decision_ms": trace.web_decision_ms,
            "search_ms": trace.web_search_ms,
            "error": trace.web_error,
            "model": model,
            "base_url": base_url,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
    return records


def _judge_input(record: dict) -> str:
    return json.dumps(
        {
            "scenario": record.get("scenario"),
            "description": record.get("description"),
            "expected_search": record.get("expected_search"),
            "conversation_context": record.get("history", []),
            "user_message": record.get("user", ""),
            "search_was_used": record.get("actual_search", False),
            "search_query": record.get("query"),
            "search_motivation": record.get("motivo"),
            "notes": record.get("search_results", []),
            "search_status": record.get("search_status"),
            "uncertainty_expected": record.get("uncertainty_expected", False),
            "reply": record.get("reply", ""),
        },
        ensure_ascii=False,
    )


async def judge_web_search_records(llm, records: list[dict]) -> list[dict]:
    """Add one semantic, phrase-agnostic judgment to each captured case."""
    for record in records:
        content = await llm.chat(
            [
                {"role": "system", "content": SEMANTIC_JUDGE_PROMPT},
                {"role": "user", "content": _judge_input(record)},
            ],
            schema=SEMANTIC_JUDGE_SCHEMA,
            max_tokens=500,
            temperature=0,
            quick_turn=True,
            strict_schema=True,
        )
        judgment = parse_semantic_judgment(content)
        record["semantic_judgment"] = judgment or {
            **{field: "not_applicable" for field in SEMANTIC_FIELDS},
            "rationale": "No se pudo interpretar el JSON del juez.",
        }
    return records
