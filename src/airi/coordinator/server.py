"""Private coordinator API; tokens and Discord identities are configured together."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
from pathlib import Path

from aiohttp import web

from .policy import ParticipationPolicy
from .store import ChannelCoordinator, Conflict


def create_app(store, tokens):
    if (
        set(tokens) != set(store.bots)
        or any(len(t) < 24 for t in tokens.values())
        or len(set(tokens.values())) != 2
    ):
        raise ValueError("Configure two distinct internal tokens of at least 24 characters")

    @web.middleware
    async def errors(request, handler):
        try:
            return await handler(request)
        except Conflict as exc:
            raise web.HTTPConflict(text=str(exc))
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text="Invalid request")

    @web.middleware
    async def auth(request, handler):
        if request.path not in ("/healthz", "/readyz"):
            credential = request.headers.get("Authorization", "").removeprefix("Bearer ")
            bot = next(
                (b for b, token in tokens.items() if hmac.compare_digest(credential, token)), None
            )
            if bot is None:
                raise web.HTTPUnauthorized()
            request["bot"] = bot
        return await handler(request)

    app = web.Application(middlewares=[errors, auth], client_max_size=128 * 1024)
    scheduler_task = None

    async def idle_scheduler(_app):
        nonlocal scheduler_task

        async def run():
            while True:
                store.tick()
                await asyncio.sleep(1)

        task = asyncio.create_task(run())
        scheduler_task = task
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app.cleanup_ctx.append(idle_scheduler)

    async def health(request):
        store.db.execute("SELECT 1")
        if scheduler_task is not None and scheduler_task.done():
            raise web.HTTPServiceUnavailable(text="Scheduler unavailable")
        return web.json_response({"status": "ok"})

    async def events(request):
        data = await request.json()
        if data.get("type") == "worker":
            store.register(
                request["bot"],
                discord_id=data["discord_id"],
                date_active=data.get("date_active", False),
                available=data.get("available", True),
            )
            return web.json_response({"ok": True})
        return web.json_response(store.ingest(data))

    async def register(request):
        data = await request.json()
        store.register(
            request["bot"],
            discord_id=data["discord_id"],
            date_active=data.get("date_active", False),
            available=data.get("available", True),
        )
        return web.json_response(
            {
                "bots": store.bots,
                "channel_id": store.channel,
                "date_owner": store.date_owner(),
                "uncertain": store.uncertain(request["bot"]),
            }
        )

    async def claim(request):
        for _ in range(20):
            job = store.claim(request["bot"])
            if job:
                return web.json_response({"job": job})
            await asyncio.sleep(0.5)
        return web.json_response({"job": None})

    async def ready(request):
        return web.json_response(store.ready(request.match_info["id"], request["bot"]))

    async def check(request):
        job = store.get_job(request.match_info["id"], request["bot"])
        valid = (
            job["status"] in ("generating", "publishing")
            and store.clock() <= job["expires"]
            and (job["status"] == "publishing" or job["revision"] == store._state()["revision"])
        )
        return web.json_response({"valid": valid})

    async def component(request):
        # Component handlers mutate date state, so reserve their turn before
        # invoking Discord's callback. Reject rather than queue expiring UI.
        store._expire()
        if store.db.execute(
            "SELECT 1 FROM jobs WHERE status IN ('queued','generating','publishing','uncertain')"
        ).fetchone():
            raise Conflict("Channel busy")
        if store.date_owner() not in (None, request["bot"]):
            raise Conflict("Another bot owns the date")
        data = await request.json()
        if data.get("content") != "!__component__" or data.get("mentions") != [
            store.bots[request["bot"]]
        ]:
            raise ValueError("Invalid component routing")
        data["component"] = True
        store.ingest(data)
        job = store.claim(request["bot"])
        if job is None:
            raise Conflict("Workers not ready")
        return web.json_response({"job": job})

    async def sending(request):
        store.sending(request.match_info["id"], request["bot"], await request.json())
        return web.json_response({"ok": True})

    async def complete(request):
        data = await request.json()
        if "date_active" in data:
            store.register(
                request["bot"],
                discord_id=store.bots[request["bot"]],
                date_active=data["date_active"],
                available=data.get("available", True),
            )
        store.complete(
            request.match_info["id"],
            request["bot"],
            outcome=data["outcome"],
            sent=data.get("sent", []),
            decision=data.get("decision"),
        )
        return web.json_response({"ok": True})

    app.router.add_get("/healthz", health)
    app.router.add_get("/readyz", health)
    app.router.add_post("/events", events)
    app.router.add_post("/workers/register", register)
    app.router.add_post("/jobs/claim", claim)
    app.router.add_post("/components/claim", component)
    app.router.add_post("/jobs/{id}/ready", ready)
    app.router.add_post("/jobs/{id}/check", check)
    app.router.add_post("/jobs/{id}/sending", sending)
    app.router.add_post("/jobs/{id}/complete", complete)
    return app


def main():
    logging.basicConfig(level=logging.INFO)
    bots = json.loads(os.environ["COORDINATOR_BOTS"])
    bots = {str(k): str(v) for k, v in bots.items()}
    path = Path(os.environ.get("COORDINATOR_DB", "data/coordinator.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    store = ChannelCoordinator(
        path,
        bots,
        channel_id=os.environ["CHANNEL_ID"],
        debounce=float(os.getenv("COORDINATOR_DEBOUNCE", "3")),
        policy=ParticipationPolicy.from_env(),
    )
    tokens = {b: os.environ[f"COORDINATOR_TOKEN_{b.upper()}"] for b in bots}
    app = create_app(store, tokens)

    async def close(_app):
        store.close()

    app.on_cleanup.append(close)
    # aiohttp's default access logger includes no body or authorization headers.
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("COORDINATOR_PORT", "8090")))
