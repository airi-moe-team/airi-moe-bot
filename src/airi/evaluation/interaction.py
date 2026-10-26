"""Evaluación de interacción natural de Airi (fase 2).

El módulo separa dos responsabilidades:

- **Generación live**: ejecuta los siete escenarios contra el LLM configurado
  usando ``ConversationService``, sin Discord y sin persistir estado real.
- **Evaluación offline**: consume registros JSONL ya generados y calcula
  métricas observables (preguntas como cierre, gestos acumulados, muletillas,
  contradicciones de estado, fallos de esquema) más la rúbrica humana 0-2.

Formato de cada registro (una línea JSON)::

    {
      "scenario": "pregunta_directa",
      "category": "direct_question",
      "turn": 1,
      "user": "Airi, ¿qué prefieres: el café o el té?",
      "reply": "Prefiero el té. Me gusta más el aroma.",
      "parse_ok": true,
      "finish_reason": "stop",
      "raw_llm": "{...}",
      "prompt_system": "...",
      "disconnect": null,
      "stay_active": true,
      "model": "...",
      "prompt_sha256": "...",
      "rubric": {
        "comprension": 2,
        "naturalidad": 2,
        "continuidad": 2,
        "individualidad": 1,
        "coherencia": 2
      }
    }

La rúbrica es opcional en la captura y se añade al revisar el JSONL. Cada
escenario vale 10 puntos (5 criterios × 0-2); los siete escenarios suman 70.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from airi.domain.affinity import default_world
from airi.domain.narrative_claims import disconnect_claim_problem
from airi.services.conversation import ConversationService
from airi.services.state import AppState

#: Reloj fijo para que el baseline y el candidato compartan referencias
#: temporales (edad de memorias, «hace X», diario). No afecta al muestreo.
EVAL_NOW = 1_700_000_000.0

RUBRIC_CRITERIA = (
    "comprension",
    "naturalidad",
    "continuidad",
    "individualidad",
    "coherencia",
)
RUBRIC_MAX_PER_SCENARIO = 10
RUBRIC_MAX_TOTAL = RUBRIC_MAX_PER_SCENARIO * 7


@dataclass(frozen=True)
class InteractionScenario:
    """Un escenario conversacional reproducible."""

    id: str
    category: str
    description: str
    turns: tuple[str, ...]
    seed_memories: tuple[str, ...] = ()


#: Los siete escenarios de la fase 2. Los nombres y textos son fixtures de
#: evaluación: no son lógica de producción ni deben usarse para reconocer
#: intenciones concretas en el bot.
INTERACTION_SCENARIOS: tuple[InteractionScenario, ...] = (
    InteractionScenario(
        "pregunta_directa",
        "direct_question",
        "Pregunta directa con opinión: elegir y argumentar antes de preguntar.",
        (
            "Airi, ¿qué prefieres: el café o el té? Dime cuál y por qué.",
        ),
    ),
    InteractionScenario(
        "correccion",
        "correction",
        "El usuario corrige una evasiva y exige una respuesta directa.",
        (
            "Airi, ¿qué prefieres: el café o el té?",
            "No me respondiste. Te pregunté qué prefieres, no que me preguntes a mí.",
        ),
    ),
    InteractionScenario(
        "saludo_breve",
        "brief_greeting",
        "Saludo breve: responder sin convertir el saludo en entrevista.",
        ("hola Airi",),
    ),
    InteractionScenario(
        "preferencia_corregida",
        "corrected_preference",
        "Corrección de un dato recordado: debe prevalecer la versión nueva.",
        (
            "Mi postre favorito es el flan.",
            "No, me equivoqué: mi postre favorito es el tiramisú.",
            "¿Qué postre crees que me gusta?",
        ),
        seed_memories=("Le encanta el flan.",),
    ),
    InteractionScenario(
        "desacuerdo",
        "disagreement",
        "Desacuerdo respetuoso: puede discrepar sin atacar ni ceder.",
        (
            "El anime me parece una pérdida de tiempo. ¿Tú qué opinas?",
            "¿Por qué lo defiendes?",
        ),
    ),
    InteractionScenario(
        "charla_casual",
        "casual",
        "Charla casual: acompañar sin interrogar ni llenar cada hueco.",
        (
            "Hoy tuve un día horrible en el trabajo.",
            "Solo quiero distraerme un rato.",
        ),
    ),
    InteractionScenario(
        "despedida",
        "farewell",
        "Despedida temporal: no fingir un apagado ni cerrar la conversación.",
        (
            "Me voy un rato, luego hablamos.",
            "Ya volví. ¿Me extrañaste?",
        ),
    ),
)


@dataclass
class EvalUser:
    """Interlocutor mínimo que espera ``ConversationService``."""

    id: int = 1
    display_name: str = "Alex"


@dataclass
class InteractionMetrics:
    turns: int = 0
    scenarios: list = field(default_factory=list)
    question_only_replies: int = 0
    repeated_closings: int = 0
    gesture_density: float = 0.0
    stacked_gestures: int = 0
    prefab_farewells: int = 0
    schema_failures: int = 0
    truncated_replies: int = 0
    state_contradictions: int = 0
    disproportionate_replies: int = 0
    rubric_total: int = 0
    rubric_scenarios_scored: int = 0

    @property
    def critical_violations(self) -> int:
        return self.schema_failures + self.truncated_replies + self.state_contradictions

    @property
    def quality_violations(self) -> int:
        return (
            self.question_only_replies
            + self.repeated_closings
            + self.stacked_gestures
            + self.prefab_farewells
            + self.disproportionate_replies
        )

    @property
    def passed(self) -> bool:
        return self.critical_violations == 0

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["critical_violations"] = self.critical_violations
        payload["quality_violations"] = self.quality_violations
        payload["rubric_max"] = RUBRIC_MAX_TOTAL
        payload["passed"] = self.passed
        return payload


_ACTION_RE = re.compile(r"\*[^*\n]+\*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
_TRAILING_PUNCT_RE = re.compile(r"[\s.!?…,;:~*_]+$")

#: Muletillas de despedida que suenan a plantilla. Se comparan sin acentos y
#: en minúsculas para no depender de la puntuación exacta.
_PREFAB_FAREWELLS = (
    "aqui estare",
    "estare aqui",
    "aqui me tienes",
    "suenos dulces",
    "manana sera otro dia",
    "siempre estare",
    "no dudes en",
    "cuando quieras hablar",
    "que tengas un buen dia",
    "aqui esperandote",
    "estare esperandote",
    "estoy aqui para escucharte",
    "estoy aqui para acompanarte",
    "aqui para escucharte",
    "aqui para acompanarte",
    "cuenta conmigo",
)


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(
        char for char in normalized if not unicodedata.combining(char)
    )


def _spoken_text(reply: str) -> str:
    """Quita las acciones narrativas entre asteriscos."""
    return _ACTION_RE.sub(" ", reply or "")


def _actions(reply: str) -> list[str]:
    return _ACTION_RE.findall(reply or "")


def _normalized_closing(reply: str) -> str:
    text = " ".join(_spoken_text(reply).split())
    if not text:
        return ""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    closing = sentences[-1] if sentences else text
    closing = _TRAILING_PUNCT_RE.sub("", closing).strip().lower()
    return " ".join(closing.split())


def _is_question_only(reply: str) -> bool:
    """True si la parte hablada termina en pregunta y no afirma nada antes."""
    text = _spoken_text(reply).strip()
    if not text or not text.endswith("?"):
        return False
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return bool(sentences) and all(sentence.endswith("?") for sentence in sentences)


def _has_prefab_farewell(reply: str) -> bool:
    normalized = _strip_accents(" ".join(_spoken_text(reply).lower().split()))
    return any(phrase in normalized for phrase in _PREFAB_FAREWELLS)


def _is_disproportionate(reply: str, user_text: str) -> bool:
    reply_len = len(_spoken_text(reply).strip())
    user_len = len((user_text or "").strip())
    return reply_len > max(280, user_len * 6)


def _rubric_value(value) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(2, score))


def _rubric_payload(raw: dict) -> dict | None:
    rubric = raw.get("rubric")
    if not isinstance(rubric, dict):
        return None
    return {key: _rubric_value(rubric.get(key)) for key in RUBRIC_CRITERIA}


def evaluate_interactions(records: Iterable[dict]) -> InteractionMetrics:
    """Calcula las métricas de naturalidad y estado de una secuencia."""
    items = [raw for raw in records if isinstance(raw, dict)]
    metrics = InteractionMetrics()
    seen_scenarios: list[str] = []
    last_closing: dict[tuple[str, int], str] = {}
    # La rúbrica es por escenario (y repetición), no por turno. Si el revisor
    # anota el mismo dict en cada turno, solo cuenta una vez.
    rubric_by_scenario: dict[tuple[str, int], dict] = {}
    gesture_count = 0

    for raw in items:
        metrics.turns += 1
        scenario = str(raw.get("scenario", "") or "")
        repeat = raw.get("repeat", 1)
        try:
            repeat = int(repeat)
        except (TypeError, ValueError):
            repeat = 1
        scenario_key = (scenario, repeat)
        if scenario and scenario not in seen_scenarios:
            seen_scenarios.append(scenario)
        reply = raw.get("reply") if isinstance(raw.get("reply"), str) else ""
        user_text = raw.get("user") if isinstance(raw.get("user"), str) else ""

        if _is_question_only(reply):
            metrics.question_only_replies += 1
        closing = _normalized_closing(reply)
        previous = last_closing.get(scenario_key, "")
        if closing and previous and closing == previous:
            metrics.repeated_closings += 1
        if closing:
            last_closing[scenario_key] = closing
        actions = _actions(reply)
        gesture_count += len(actions)
        if len(actions) >= 2:
            metrics.stacked_gestures += 1
        if _has_prefab_farewell(reply):
            metrics.prefab_farewells += 1
        if _is_disproportionate(reply, user_text):
            metrics.disproportionate_replies += 1

        if raw.get("parse_ok") is False or raw.get("valid") is False:
            metrics.schema_failures += 1
        if str(raw.get("finish_reason", "") or "").lower() == "length":
            metrics.truncated_replies += 1

        disconnect = raw.get("disconnect")
        leave = bool(isinstance(disconnect, dict) and disconnect.get("leave"))
        if disconnect_claim_problem(reply, leave):
            metrics.state_contradictions += 1

        rubric = _rubric_payload(raw)
        if rubric is not None and scenario:
            rubric_by_scenario[scenario_key] = rubric

    replies = metrics.turns
    metrics.gesture_density = round(gesture_count / replies, 3) if replies else 0.0

    for rubric in rubric_by_scenario.values():
        metrics.rubric_total += sum(rubric.values())
        metrics.rubric_scenarios_scored += 1

    metrics.scenarios = seen_scenarios
    return metrics


def compare_interactions(baseline: Iterable[dict], candidate: Iterable[dict]) -> dict:
    """Compara baseline y candidato; ``regression`` solo marca daño crítico."""
    base = evaluate_interactions(baseline)
    cand = evaluate_interactions(candidate)
    delta = {
        key: getattr(cand, key) - getattr(base, key)
        for key in (
            "turns",
            "question_only_replies",
            "repeated_closings",
            "gesture_density",
            "stacked_gestures",
            "prefab_farewells",
            "schema_failures",
            "truncated_replies",
            "state_contradictions",
            "disproportionate_replies",
            "rubric_total",
            "rubric_scenarios_scored",
        )
    }
    quality_keys = (
        "question_only_replies",
        "repeated_closings",
        "stacked_gestures",
        "prefab_farewells",
        "disproportionate_replies",
    )
    critical_keys = (
        "schema_failures",
        "truncated_replies",
        "state_contradictions",
    )
    critical_regression = any(delta[key] > 0 for key in critical_keys)
    quality_regression = any(delta[key] > 0 for key in quality_keys)
    return {
        "baseline": base.to_dict(),
        "candidate": cand.to_dict(),
        "delta": delta,
        "rubric_delta": cand.rubric_total - base.rubric_total,
        "critical_regression": critical_regression,
        "quality_regression": quality_regression,
        "regression": critical_regression,
    }


def load_records(path) -> list[dict]:
    """Carga un JSONL de registros de interacción."""
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            records.append(value)
    return records


def write_records(path, records: Iterable[dict]) -> None:
    """Guarda registros en JSONL, creando el directorio si hace falta."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _fresh_state(scenario: InteractionScenario) -> AppState:
    memories = {}
    if scenario.seed_memories:
        memories["1"] = [
            {"text": text, "created_at": EVAL_NOW}
            for text in scenario.seed_memories
        ]
    return AppState(world=default_world(), memories=memories)


def _llm_metadata(llm, base_url: str | None, model: str | None) -> dict:
    resolved_model = (
        model
        or getattr(llm, "model", None)
        or os.environ.get("LLM_MODEL", "")
        or "unknown"
    )
    resolved_base = (
        base_url
        or getattr(llm, "base_url", None)
        or os.environ.get("LLM_BASE_URL", "http://127.0.0.1:7000")
    )
    temperature = getattr(llm, "temperature", None)
    return {
        "model": resolved_model,
        "base_url": resolved_base,
        "temperature": temperature,
    }


async def _generate_records(
    *,
    llm,
    scenarios: tuple[InteractionScenario, ...],
    repeat: int,
    now: float,
    base_url: str | None,
    model: str | None,
) -> list[dict]:
    from airi.evaluation.runner import run_scenario

    metadata = _llm_metadata(llm, base_url, model)
    records: list[dict] = []
    for run_index in range(1, max(1, int(repeat)) + 1):
        for scenario in scenarios:
            state = _fresh_state(scenario)
            service = ConversationService(
                llm=llm,
                state=state,
                clock=lambda: now,
            )
            scenario_records = await run_scenario(
                scenario,
                service,
                EvalUser(),
                now=now,
                turn_prefix=f"eval{run_index}",
            )
            for record in scenario_records:
                prompt = record.get("prompt_system") or ""
                record["repeat"] = run_index
                record["scenario_description"] = scenario.description
                record["prompt_sha256"] = hashlib.sha256(
                    prompt.encode("utf-8")
                ).hexdigest()
                record.update(metadata)
                record["generated_at"] = datetime.now(timezone.utc).isoformat()
                records.append(record)
    return records


async def generate_live_records(
    *,
    llm=None,
    scenarios: tuple[InteractionScenario, ...] = INTERACTION_SCENARIOS,
    repeat: int = 1,
    now: float = EVAL_NOW,
    base_url: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """Genera los escenarios contra un LLM real o inyectado.

    Si ``llm`` es ``None`` se construye un ``HttpLlmClient`` con la config del
    entorno (o con ``base_url``/``model`` explícitos). No toca Discord ni
    persiste el estado: cada escenario parte de un ``AppState`` limpio.
    """
    if llm is not None:
        return await _generate_records(
            llm=llm,
            scenarios=scenarios,
            repeat=repeat,
            now=now,
            base_url=base_url,
            model=model,
        )

    import aiohttp

    from airi.adapters.http_llm import build_llm

    async with aiohttp.ClientSession() as session:
        client = build_llm(session, base_url=base_url, model=model)
        return await _generate_records(
            llm=client,
            scenarios=scenarios,
            repeat=repeat,
            now=now,
            base_url=base_url,
            model=model,
        )
