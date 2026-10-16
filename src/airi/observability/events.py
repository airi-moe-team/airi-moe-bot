"""Eventos de trazas: TurnEvent y utilidades de serialización.

Este módulo contiene el dataclass TurnEvent y funciones de serialización
que antes estaban en `trace.py`.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Límites anti-disco: una traza nunca debería pasar de unas decenas de KB.
MAX_SYSTEM_PROMPT_CHARS = 60_000
MAX_HISTORY_CHARS = 30_000
MAX_WEB_CONTEXT_CHARS = 12_000
MAX_RAW_LLM_CHARS = 20_000

TRACE_VERSION = 1


def _clip(value, limit):
    """Recorta strings (o listas de dicts con 'content') a `limit` chars."""
    if isinstance(value, str):
        if len(value) > limit:
            return value[:limit] + f"…[truncado {len(value) - limit} chars]"
        return value
    if isinstance(value, list):
        out = []
        budget = limit
        for item in value:
            if budget <= 0:
                out.append({"__truncated__": "…[resto del historial truncado]"})
                break
            rendered = json.dumps(item, ensure_ascii=False, default=str)
            if len(rendered) > budget:
                item = dict(item)
                content = str(item.get("content", ""))
                keep = max(0, budget - 64)
                item["content"] = content[:keep] + "…[truncado]"
                item["__truncated__"] = True
                out.append(item)
                break
            out.append(item)
            budget -= len(rendered)
        return out
    return value


@dataclass
class TurnEvent:
    """Evento completo de un turno, serializable a JSON sin pérdida.

    Cubre mensajes, regalos, acciones de cita, selección de escena y comandos
    (`kind`). Los `state_snapshot_*` se rellenan ANTES de cualquier mutación
    para que `airi.replay` pueda reconstruir el estado exacto del turno.
    """

    version: int = TRACE_VERSION
    kind: str = "message"

    # Identidad y tiempos
    correlation_id: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    total_latency_ms: int = 0

    # Entrada
    user_id: str = ""
    user_name: str = ""
    channel_id: str = ""
    in_date: bool = False
    date_state: str | None = None
    allow_web: bool = True
    raw_input: str = ""
    messages_in: list = field(default_factory=list)
    history_in: list = field(default_factory=list)

    # Contexto reconstruido
    prompt_system: str = ""
    web_query: str | None = None
    web_context: str | None = None

    # Respuesta del LLM
    raw_llm: str | None = None
    llm_finish_reason: str | None = None
    llm_usage: dict | None = None
    llm_latency_ms: int = 0
    llm_ms: int = 0  # alias legacy de llm_latency_ms
    # Presupuesto de contexto: estimación del prompt y si hubo recorte.
    prompt_tokens_est: int = 0
    history_trimmed: bool = False
    output_truncated: bool = False  # finish_reason == "length"

    # Parseo
    parsed: dict = field(default_factory=dict)
    parse_ok: bool = True
    parse_warnings: list = field(default_factory=list)
    grounded: bool = True

    # Resultado
    final_reply: str = ""

    # GIF
    gif: str = "none"
    gif_sent: bool = False
    gif_fetched: bool = False  # alias legacy de gif_sent
    gif_error: str | None = None

    # Memoria / diario
    memory_saved: str | None = None
    diary_saved: str | None = None

    # Afinidad
    affinity_before: int = 0
    affinity_after: int = 0
    affinity_delta_requested: int = 0
    affinity_applied: int = 0
    affinity_event: str = "none"
    level_before: str = ""
    level_after: str = ""
    leveled_up: bool = False

    # Identidad mutable
    self_changed: bool = False
    self_update_action: dict | None = None

    # Cita
    date_decision: str = "continue"
    date_event: str | None = None
    date_turns_before: int = 0
    date_turns_after: int = 0
    date_end_keyword: str | None = None
    date_question_forced: bool = False
    date_question_invalid: bool = False

    # Errores y notas
    skipped: bool = False
    error: str | None = None
    errors: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    timings_ms: dict = field(default_factory=dict)

    # Snapshots de estado previos al turno (para replay fiel)
    state_snapshot_affinity: dict = field(default_factory=dict)
    state_snapshot_world: dict = field(default_factory=dict)
    state_snapshot_memories: list = field(default_factory=list)
    state_snapshot_diary: list = field(default_factory=list)
    state_snapshot_date: dict | None = None

    # ------------------------------------------------------------------
    # Alias de compatibilidad con las trazas antiguas (TurnTrace)
    # ------------------------------------------------------------------

    @property
    def reply(self) -> str:
        """Alias de `final_reply` (compatibilidad con trazas v1)."""
        return self.final_reply

    @reply.setter
    def reply(self, value: str) -> None:
        self.final_reply = value

    @property
    def turn_ms(self) -> int:
        """Alias de `total_latency_ms` (compatibilidad con trazas v1)."""
        return self.total_latency_ms

    @turn_ms.setter
    def turn_ms(self, value: int) -> None:
        self.total_latency_ms = value

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def finish(self) -> "TurnEvent":
        """Marca el fin del turno y calcula `total_latency_ms`."""
        self.finished_at = time.time()
        if self.started_at:
            self.total_latency_ms = int(
                (self.finished_at - self.started_at) * 1000
            )
        return self

    def to_dict(self, *, keep_raw=True, full_prompt=True):
        """Diccionario JSON-safe, con recortes anti-disco.

        - `keep_raw=False`: no guarda `raw_llm` (la traza deja de ser
          reproducible y `replay` lo detecta).
        """
        data = asdict(self)
        data["prompt_system"] = _clip(data["prompt_system"], MAX_SYSTEM_PROMPT_CHARS)
        data["history_in"] = _clip(data["history_in"], MAX_HISTORY_CHARS)
        data["messages_in"] = _clip(data["messages_in"], 4_000)
        if data.get("web_context"):
            data["web_context"] = _clip(data["web_context"], MAX_WEB_CONTEXT_CHARS)
        if not keep_raw:
            data["raw_llm"] = None
            data["reproducible"] = False
        else:
            data["raw_llm"] = _clip(data["raw_llm"], MAX_RAW_LLM_CHARS)
            data["reproducible"] = data["raw_llm"] is not None
        void = [k for k, v in data.items() if v is None and k != "raw_llm"]
        for k in void:
            del data[k]
        return data

    def to_json(self, indent: int | None = 2) -> str:
        """Serializa el evento a JSON (recortes anti-disco incluidos)."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data):
        """Reconstruye el evento ignorando claves desconocidas (forward-compat).

        Traduce las claves de las trazas v1 (`reply`, `turn_ms`) a los campos
        actuales (`final_reply`, `total_latency_ms`).
        """
        data = dict(data)
        if "reply" in data and "final_reply" not in data:
            data["final_reply"] = data.pop("reply")
        if "turn_ms" in data and "total_latency_ms" not in data:
            data["total_latency_ms"] = data.pop("turn_ms")
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


# Alias de compatibilidad: el evento antes se llamaba TurnTrace.
TurnTrace = TurnEvent


def trace_path(trace_dir, correlation_id, *, now=None):
    """Ruta `TRACE_DIR/YYYY-MM-DD/<cid>.json` (sin crear directorios)."""
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    safe_cid = "".join(c for c in correlation_id if c.isalnum() or c in "-_") or "x"
    return os.path.join(trace_dir, day, f"{safe_cid}.json")


def save_turn_trace(trace, trace_dir, *, keep_raw=True):
    """Guarda la traza en disco. Best-effort: nunca lanza excepciones.

    Devuelve la ruta del fichero o None si el guardado está desactivado
    (`trace_dir` vacío) o falló.
    """
    if not trace_dir:
        return None
    try:
        path = trace_path(trace_dir, trace.correlation_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(trace.to_dict(keep_raw=keep_raw), fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return path
    except OSError:
        log.exception("No se pudo guardar la traza del turno")
        return None


def load_turn_trace(path) -> TurnEvent:
    """Carga un evento desde disco (lanza si el fichero es inválido)."""
    with open(path, "r", encoding="utf-8") as fh:
        return TurnEvent.from_dict(json.load(fh))


# Alias histórico.
load_turn_event = load_turn_trace
