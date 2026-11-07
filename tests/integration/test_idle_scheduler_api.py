import asyncio
from datetime import datetime, timezone

from aiohttp.test_utils import TestClient, TestServer

from airi.coordinator.policy import ParticipationPolicy
from airi.coordinator.server import create_app
from airi.coordinator.store import ChannelCoordinator


def test_background_scheduler_and_http_decision_protocol(tmp_path):
    async def scenario():
        now = [datetime(2026, 11, 7, 15, tzinfo=timezone.utc).timestamp()]
        store = ChannelCoordinator(
            tmp_path / "coordinator.sqlite3",
            {"airi": "10", "luna": "20"},
            channel_id="7",
            clock=lambda: now[0],
            policy=ParticipationPolicy(idle_seconds=1, recheck_seconds=1, max_interventions=1),
        )
        client = TestClient(TestServer(create_app(store, {"airi": "a" * 24, "luna": "b" * 24})))
        await client.start_server()

        async def post(path, data=None, bot="airi"):
            return await client.post(
                path,
                json=data or {},
                headers={
                    "Authorization": "Bearer " + ("a" if bot == "airi" else "b") * 24,
                },
            )

        async def register():
            for bot, uid in store.bots.items():
                assert (await post("/workers/register", {"discord_id": uid}, bot)).status == 200

        try:
            await register()
            now[0] += 1
            await register()
            await asyncio.sleep(1.1)
            decision = (await (await post("/jobs/claim")).json())["job"]
            assert decision["kind"] == "decision" and decision["target_kind"] == "proactive"
            assert (await post(f"/jobs/{decision['id']}/ready")).status == 409
            assert (
                await post(
                    f"/jobs/{decision['id']}/complete",
                    {
                        "outcome": "decision",
                        "decision": {"participate": False, "reason_code": "no_contribution"},
                    },
                )
            ).status == 200
            assert not store._busy()
            assert store._state()["daily_counts"] == {}
            now[0] += 1
            await register()
            await asyncio.sleep(1.1)
            decision = (await (await post("/jobs/claim", bot="luna")).json())["job"]
            assert decision["bot"] == "luna"
            assert (
                await post(
                    f"/jobs/{decision['id']}/complete",
                    {
                        "outcome": "decision",
                        "decision": {"participate": True, "reason_code": "sibling"},
                    },
                    "luna",
                )
            ).status == 200
            generation = (await (await post("/jobs/claim", bot="luna")).json())["job"]
            assert generation["kind"] == "proactive"
            assert "author_id" not in generation
            assert (await post(f"/jobs/{generation['id']}/ready", bot="luna")).status == 200
            assert (
                await post(f"/jobs/{generation['id']}/sending", {"content": "hola hermana"}, "luna")
            ).status == 200
            assert (
                await post(
                    f"/jobs/{generation['id']}/complete",
                    {
                        "outcome": "published",
                        "sent": ["100"],
                    },
                    "luna",
                )
            ).status == 200
            assert store._state()["daily_counts"]["2026-11-07"] == 1
            assert not store._busy()
        finally:
            await client.close()
            store.close()

    asyncio.run(scenario())
