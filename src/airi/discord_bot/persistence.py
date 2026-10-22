"""Ayudantes de transacción para comandos de Discord."""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager, nullcontext


@contextmanager
def state_transaction(ctx):
    """Usa la transacción de persistencia si el contexto la tiene.

    Los tests y contextos antiguos que no inyectan persistencia conservan el
    comportamiento previo de guardado inmediato.
    """
    persistence = getattr(ctx, "persistence", None)
    if persistence is None:
        with nullcontext():
            yield
        return
    with persistence.transaction():
        yield


@asynccontextmanager
async def async_state_transaction(ctx):
    """Igual que `state_transaction`, pero toma el candado de commit."""
    lock = getattr(ctx, "commit_lock", None)
    async with (lock or nullcontext()):
        with state_transaction(ctx):
            yield
