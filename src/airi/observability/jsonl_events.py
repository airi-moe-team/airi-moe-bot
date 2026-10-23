"""Eventos JSONL para observabilidad de interacciones de Discord.

El registro es un stream de un objeto JSON por linea, en nivel INFO, que recorre
cada interaccion sin exponer contenido sensible. El estado global y los
estados de los modulos se acaban en un `interaction_summary` final.

Estados terminales de un modulo:
- activated: se ejecuto y produjo un resultado resumido.
- skipped: se omitio por la ruta tomada (por ejemplo, un comando ya manejado).
- disabled: el modulo no esta habilitado para esta instancia.
- not_applicable: el modulo no es aplicable a esta interaccion.
- failed: el modulo se ejecuto yorio un error controlado.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping

log = logging.getLogger(__name__)


def _jsonl_logger() -> logging.Logger:
    """Logger dedicado para emitir JSONL sin prefijo de formato."""
    logger = logging.getLogger("airi.observability.jsonl")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def install_jsonl_logging() -> logging.Logger:
    """Configura (idempotente) el logger JSONL usado en `airi run`."""
    return _jsonl_logger()

SCHEMA = "airi.log.v1"
LEVEL = "INFO"

EVENT_START = "interaction_start"
EVENT_MODULE_RESULT = "module_result"
EVENT_MODULE_ERROR = "module_error"
EVENT_SUMMARY = "interaction_summary"

STATES = ("activated", "skipped", "disabled", "not_applicable", "failed")

REASON_CODES = {
    "activated": None,
    "skipped": "none",
    "disabled": "discontinued",
    "not_applicable": "not_requested",
    "failed": "error",
}

SENSITIVE_KEYS = frozenset(
    {
        "token",
        "tokens",
        "key",
        "keys",
        "secret",
        "secrets",
        "secret_key",
        "private_key",
        "password",
        "passwd",
        "authorization",
        "authorization_header",
        "cookie",
        "credential",
        "credentials",
        "apikey",
        "api_key",
        "x_api_key",
        "x-api-key",
        "bearer",
        "prompt",
        "prompts",
        "content",
        "messages",
        "message",
        "reply",
        "raw_input",
        "raw_output",
        "raw_llm",
        "history",
        "history_in",
        "history_out",
    }
)

DEFAULT_CATALOG = (
    "discord_input",
    "commands",
    "debounce",
    "spectator",
    "citas",
    "regalos",
    "conversation",
    "web_search",
    "llm_call",
    "parsing",
    "grounding",
    "relationships",
    "memory",
    "diary",
    "gifts",
    "persistence",
    "publication",
    "traces",
)


def now_iso() -> str:
    """Timestamp UTC ISO-8601 con sufijo Z."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def event_line(event: str, interaction_id: str, **fields) -> str:
    """Compone un objeto JSON valido y lo devuelve serializado como texto."""
    payload = {
        "schema": SCHEMA,
        "ts": now_iso(),
        "level": LEVEL,
        "interaction_id": interaction_id,
        **fields,
    }
    return _json({"event": event, **payload})


def build_start(interaction_id: str) -> str:
    return event_line(EVENT_START, interaction_id)


def build_module_result(
    interaction_id: str,
    module: str,
    status: str,
    *,
    reason_code: str | None = None,
    duration_ms: float = 0.0,
    **details,
) -> str:
    if status not in STATES:
        raise ValueError('status ' + repr(status) + ' no es un estado terminal valido')
    reason_code = reason_code or REASON_CODES[status]
    payload = {
        "module": module,
        "status": status,
        "reason_code": reason_code,
        "duration_ms": duration_ms,
        **details,
    }
    return event_line(EVENT_MODULE_RESULT, interaction_id, **payload)


def build_module_error(
    interaction_id: str,
    module: str,
    error_type: str,
    message: str,
    **details,
) -> str:
    payload = {
        "module": module,
        "status": "failed",
        "error_type": error_type,
        "error_message": message,
        **details,
    }
    return event_line(EVENT_MODULE_ERROR, interaction_id, **payload)


def build_summary(
    interaction_id: str,
    modules: Mapping[str, "ModuleResult"],
    *,
    total_ms: float = 0.0,
    catalog: Iterable[str] | None = None,
) -> str:
    module_map = dict(modules)
    for module in catalog or ():
        module_map.setdefault(
            module,
            ModuleResult(status="skipped", reason_code="not_requested", duration_ms=0.0),
        )
    payload = {
        "total_ms": total_ms,
        "modules": {name: result.to_dict() for name, result in module_map.items()},
    }
    return event_line(EVENT_SUMMARY, interaction_id, **payload)


def sanitize_event(event: Mapping) -> dict:
    """Quita campos susceptibles de contener datos sensibles de un evento."""
    return _strip_sensitive(dict(event))


def _strip_sensitive(data) -> object:
    if isinstance(data, dict):
        out: dict = {}
        for key, value in data.items():
            if isinstance(key, str) and key.lower() in SENSITIVE_KEYS:
                continue
            out[key] = _strip_sensitive(value)
        return out
    if isinstance(data, list):
        return [_strip_sensitive(item) for item in data]
    return data


def _json(payload: Mapping) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class ModuleResult:
    status: str
    reason_code: str | None = None
    duration_ms: float = 0.0
    error_type: str | None = None
    error_message: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "duration_ms": self.duration_ms,
            "error_type": self.error_type,
            "error_message": self.error_message,
            **dict(self.details),
        }


@dataclass
class InteractionTracker:
    interaction_id: str
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    total_ms: float = 0.0
    modules: dict[str, ModuleResult] = field(default_factory=dict)

    def record(self, module: str, status: str, *, reason_code: str | None = None, **state) -> ModuleResult:
        if status not in STATES:
            raise ValueError('status ' + repr(status) + ' no es un estado terminal valido')
        reason_code = reason_code or REASON_CODES[status]
        details = state.pop("details", None)
        if details is None:
            details = {k: v for k, v in state.items() if not k.startswith("_")}
        result = ModuleResult(
            status=status,
            reason_code=reason_code,
            duration_ms=state.get("duration_ms", 0.0),
            error_type=state.get("error_type"),
            error_message=state.get("error_message"),
            details=details,
        )
        self.modules[module] = result
        return result

    def finish(self, *, duration_ms: float | None = None) -> "InteractionTracker":
        self.finished_at = time.time()
        self.total_ms = float(duration_ms if duration_ms is not None else (self.finished_at - self.started_at) * 1000.0)
        return self

    def to_summary(self) -> dict:
        return {
            "interaction_id": self.interaction_id,
            "event": EVENT_SUMMARY,
            "total_ms": self.total_ms,
            "modules": {name: result.to_dict() for name, result in self.modules.items()},
        }


class JsonlInteractionLogger:
    """Emite eventos JSONL de una interaccion a traves de un logger estandar.

    El logger nunca lanza: si la serializacion o la escritura fallan, el error
    se registra y el flujo de la aplicacion continua.
    """

    def __init__(
        self,
        interaction_id: str,
        *,
        logger: logging.Logger | None = None,
        catalog: Iterable[str] | None = None,
    ) -> None:
        self.interaction_id = interaction_id
        self.logger = logger or _jsonl_logger()
        self.catalog = tuple(catalog or DEFAULT_CATALOG)
        self.tracker = InteractionTracker(interaction_id)

    def start(self) -> str:
        line = build_start(self.interaction_id)
        self._emit(line)
        return line

    def module_result(self, module: str, status: str, *, reason_code: str | None = None, **state) -> str:
        line = build_module_result(self.interaction_id, module, status, reason_code=reason_code, **state)
        self.tracker.record(module, status, reason_code=reason_code, **state)
        self._emit(line)
        return line

    def error(self, module: str, error_type: str, message: str, **state) -> str:
        line = build_module_error(self.interaction_id, module, error_type, message, **state)
        self.tracker.record(module, "failed", reason_code="error", error_type=error_type, error_message=message, **state)
        self._emit(line)
        return line

    def summary(self, *, duration_ms: float | None = None) -> str:
        self.tracker.finish(duration_ms=duration_ms)
        line = build_summary(self.interaction_id, self.tracker.modules, total_ms=self.tracker.total_ms, catalog=self.catalog)
        self._emit(line)
        return line

    def _emit(self, line: str) -> None:
        try:
            sanitized = sanitize_event(json.loads(line))
            text = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
            self.logger.info(text)
        except Exception:
            log.exception("No se pudo emitir el evento JSONL para %s", self.interaction_id)
