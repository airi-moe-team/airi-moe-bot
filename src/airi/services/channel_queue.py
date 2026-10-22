"""Orden FIFO de trabajos por canal, sin bloqueo global."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

Job = Callable[[], Awaitable[None]]


class DispatcherClosedError(RuntimeError):
    """El canal ya no acepta trabajos."""


class ChannelDispatcher:
    """Un trabajador FIFO por canal.

    La deduplicación durable no vive aquí: el llamador reclama el mensaje en
    `TurnJournal` antes de enviar el trabajo.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._closed: set[str] = set()

    async def submit(
        self,
        channel_id: object,
        job: Job,
        *,
        message_ids: object = None,
    ) -> None:
        del message_ids  # el llamador ya reclamó los IDs en el journal
        key = str(channel_id)
        if key in self._closed:
            raise DispatcherClosedError(f"el canal {key} está cerrado")
        queue, worker = self._ensure_worker(key)
        if worker.done():
            # Un trabajador terminado no puede atender la cola.
            self._workers.pop(key, None)
            queue, worker = self._ensure_worker(key)
        future = asyncio.get_running_loop().create_future()
        await queue.put((future, job))
        await future

    async def close(self, channel_id: object) -> None:
        key = str(channel_id)
        if key in self._closed:
            return
        self._closed.add(key)
        queue = self._queues.get(key)
        worker = self._workers.get(key)
        if queue is not None:
            await queue.put(None)
        if worker is not None:
            try:
                await worker
            except asyncio.CancelledError:
                pass
        self._queues.pop(key, None)
        self._workers.pop(key, None)

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _ensure_worker(self, key: str):
        queue = self._queues.get(key)
        if queue is None:
            queue = asyncio.Queue()
            self._queues[key] = queue
        worker = self._workers.get(key)
        if worker is None or worker.done():
            worker = asyncio.create_task(self._worker(key, queue))
            self._workers[key] = worker
        return queue, worker

    async def _worker(self, key: str, queue: asyncio.Queue) -> None:
        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                future, job = item
                try:
                    await job()
                except Exception as exc:
                    log.exception("Trabajo del canal %s falló", key)
                    if not future.done():
                        future.set_exception(exc)
                else:
                    if not future.done():
                        future.set_result(None)
            finally:
                queue.task_done()
