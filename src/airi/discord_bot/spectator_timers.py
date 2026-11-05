"""Temporizadores de la sesión conversacional activa.

Centraliza el armado del temporizador de inactividad que devuelve un canal
de Activa a Espectadora. Vive en la capa Discord porque crea tareas asyncio
y usa el despachador serializado por canal; el dominio solo decide el retiro.
"""

from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger(__name__)


def arm_active_timer(
    *,
    registry,
    timers,
    dispatcher,
    channel_id,
    timeout=None,
    clock=time.time,
):
    """Arma (o rearma) el retiro por inactividad de un canal activo.

    Devuelve True si quedó armado. No arma nada si faltan las piezas de la
    capa Discord o si el timeout es <= 0: en ese caso el retiro está
    deshabilitado y el canal no debe quedarse Activo indefinidamente.
    """
    if registry is None or timers is None or dispatcher is None:
        return False
    if timeout is None:
        timeout = getattr(registry, "active_idle_seconds", 0.0)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        return False
    if timeout <= 0:
        return False

    key = (str(channel_id), "active")
    previous = timers.pop(key, None)
    if previous is not None:
        previous.cancel()

    generation = registry.session(channel_id).generation

    async def _active_timer():
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return

        async def _job():
            if registry.retire_if_idle(channel_id, generation, clock(), timeout):
                log.info("Retirada por inactividad en canal %s", channel_id)

        try:
            await dispatcher.submit(channel_id, _job)
        except Exception:
            log.exception("No se pudo procesar el retiro por inactividad")

    timers[key] = asyncio.create_task(_active_timer())
    return True


__all__ = ["arm_active_timer"]
