"""Orden FIFO y concurrencia por canal (tarea 5.2)."""

from __future__ import annotations

import asyncio

import pytest

from airi.services.channel_queue import ChannelDispatcher, DispatcherClosedError


def run(coro):
    return asyncio.run(coro)


def test_jobs_run_in_submission_order():
    async def scenario():
        dispatcher = ChannelDispatcher()
        seen = []

        async def job(index):
            await asyncio.sleep(0)
            seen.append(index)

        tasks = [
            asyncio.create_task(dispatcher.submit(7, lambda i=i: job(i)))
            for i in range(5)
        ]
        await asyncio.gather(*tasks)
        await dispatcher.close(7)
        return seen

    assert run(scenario()) == [0, 1, 2, 3, 4]


def test_channels_do_not_block_each_other():
    async def scenario():
        dispatcher = ChannelDispatcher()
        release = asyncio.Event()
        started = asyncio.Event()
        done = asyncio.Event()

        async def slow():
            started.set()
            await release.wait()

        async def fast():
            done.set()

        slow_task = asyncio.create_task(dispatcher.submit("A", slow))
        await started.wait()
        fast_task = asyncio.create_task(dispatcher.submit("B", fast))
        await asyncio.wait_for(done.wait(), timeout=1.0)
        release.set()
        await asyncio.gather(slow_task, fast_task)
        await dispatcher.close("A")
        await dispatcher.close("B")

    run(scenario())


def test_failure_does_not_block_next_job():
    async def scenario():
        dispatcher = ChannelDispatcher()
        seen = []

        async def boom():
            raise RuntimeError("fallo")

        async def ok():
            seen.append("ok")

        with pytest.raises(RuntimeError):
            await dispatcher.submit(7, boom)
        await dispatcher.submit(7, ok)
        await dispatcher.close(7)
        return seen

    assert run(scenario()) == ["ok"]


def test_closed_channel_rejects_new_jobs():
    async def scenario():
        dispatcher = ChannelDispatcher()
        await dispatcher.close(7)
        with pytest.raises(DispatcherClosedError):
            await dispatcher.submit(7, lambda: asyncio.sleep(0))

    run(scenario())
