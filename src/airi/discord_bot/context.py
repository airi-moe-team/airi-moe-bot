"""Contexto de ejecución que la capa Discord recibe inyectado.

El composition root (`bot.py`) construye un `BotContext` por mensaje/turno y lo
pasa a los comandos y al traductor de turnos. Así la capa Discord no importa
`bot` (evita ciclos) y los tests pueden construir un contexto con dobles.

La mayor parte del estado vive en `AppState` (afinidad, mundo, citas, diario,
memorias, usuarios, historiales + callbacks de persistencia). Aquí solo se
añaden los "pegamentos" que resuelven globales de `bot.py` en tiempo de llamada
(para que los monkeypatch de los tests sigan funcionando).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from airi.services.state import AppState


def _noop(*args, **kwargs):
    return None


def _noop_bool(*args, **kwargs) -> bool:
    return False


async def _anoop(*args, **kwargs):
    return None


@dataclass
class BotContext:
    channel_id: int
    state: AppState
    lock: Any = None
    owner_id: int = 0
    debounce_seconds: float = 2.5
    request_timeout: int = 300
    llm_base_url: str = "http://127.0.0.1:7000"
    # Perfil y política de health check del backend configurado.
    llm_provider: str = "llama"
    llm_health_check: bool = True
    # Observabilidad (Fase 5): si `trace_dir` está definido, cada turno se
    # guarda en `TRACE_DIR/YYYY-MM-DD/<cid>.json`.
    trace_dir: str = ""
    # Diagnóstico seguro del almacén (sin datos privados).
    storage_info: dict = field(default_factory=dict)
    # Servicios de persistencia/archivo disponibles en producción.
    persistence: Any = None
    season_archiver: Any = None
    retention: Any = None
    turn_journal: Any = None
    commit_lock: Any = None

    build_service: Callable[..., Any] = _noop
    settle_relationship: Callable[..., Any] = _anoop
    process_date_turn: Callable[..., Any] = _anoop
    add_diary_reflection: Callable[..., Any] = _noop
    send_long_message: Callable[..., Any] = _anoop
    send_gif_bytes: Callable[..., Any] = _anoop
    judge_gift: Callable[..., Any] = _anoop
    propose_scenes: Callable[..., Any] = _anoop
    reset_conversation: Callable[..., Any] = _noop
    affinity_footer: Callable[..., str] = lambda user: ""
    busy_date_owner: Callable[..., Any] = _noop
    notify_busy: Callable[..., Any] = _anoop
    date_busy_text: Callable[..., Any] = _noop
    expire_stale_dates: Callable[..., Any] = _noop
    handle_scene_choice: Callable[..., Any] = _anoop
    handle_date_action: Callable[..., Any] = _anoop
    # Pregunta decisiva de la cita: publicar, resolver y caducar.
    handle_question_answer: Callable[..., Any] = _anoop
    resolve_question: Callable[..., Any] = _noop
    apply_question_result: Callable[..., Any] = _noop
    expire_question: Callable[..., Any] = _noop
    log_diary_event: Callable[..., Any] = _noop_bool
    # Cierre global solicitado por Airi (None/False fuera de producción).
    request_shutdown: Callable[..., Any] = _anoop
    is_shutting_down: Callable[[], bool] = lambda: False
    # Marca como entregado el motivo del último cierre tras confirmar el turno.
    acknowledge_reconnect_context: Callable[..., Any] = _anoop
    maybe_reflect: Callable[..., Any] = _anoop

    def remember_trace(self, trace):
        """Persiste la traza en el TraceStore compartido (cross-message)."""
        if trace is None or self.state.traces is None:
            return
        self.state.traces._ring.append(trace)

    def last_trace_for(self, channel_id, user_id):
        """Última traza de ese (canal, usuario) en el TraceStore compartido."""
        cid, uid = str(channel_id), str(user_id)
        for ev in self.state.traces.all():
            if str(ev.channel_id) == cid and str(ev.user_id) == uid:
                return ev
        return None
