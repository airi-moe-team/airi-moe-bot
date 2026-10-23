"""Seguimiento correlacionado de una interaccion para el registro JSONL.

Une el identificador de correlacion existente (`airi.logging_setup.correlation_id`)
con el registro JSONL, garantizando que el inicio, los resultados de los
modulos y el resumen final se emita en un mismo haz, sin romper el flujo si
falla la escritura de logs.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from contextvars import ContextVar
from typing import Iterable

from airi.logging_setup import get_correlation_id, reset_correlation_id, set_correlation_id
from airi.observability import jsonl_events as jl

log = logging.getLogger(__name__)

_tracker_var: ContextVar["jl.JsonlInteractionLogger | None"] = ContextVar(
    "jsonl_tracker", default=None
)


def current_tracker() -> "jl.JsonlInteractionLogger | None":
    return _tracker_var.get()


def set_tracker(tracker: "jl.JsonlInteractionLogger | None") -> None:
    return _tracker_var.set(tracker)


@contextlib.contextmanager
def tracked_interaction(
    correlation_id: str | None = None,
    *,
    logger: jl.JsonlInteractionLogger | None = None,
    catalog: Iterable[str] | None = None,
):
    """Context manager que emite inicio, eventos y resumen JSONL en un haz.

    Uso tipico:

        with tracked_interaction(correlation_id=cid, catalog=CATALOG) as log:
            log.module_result("conversation", "activated", duration_ms=12.0)
            log.module_result("llm_call", "skipped", reason_code="not_requested")

    El contexto garantiza que `start` se emita al entrar y que `summary` se
    emita al salir, incluso si una exception aborta el procesamiento.
    """
    if correlation_id is None:
        correlation_id = uuid.uuid4().hex[:12]
        correlation_token = set_correlation_id(correlation_id)
    else:
        correlation_token = None
    if logger is None:
        logger = jl.JsonlInteractionLogger(correlation_id, catalog=catalog)
    tracker_token = set_tracker(logger)
    try:
        logger.start()
        yield logger
    finally:
        try:
            logger.summary()
        except Exception:
            log.exception(
                "No se pudo emitir el resumen de la interaccion %s", correlation_id
            )
        _tracker_var.reset(tracker_token)
        if correlation_token is not None:
            reset_correlation_id(correlation_token)
