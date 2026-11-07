"""Real HTTP scheduler and two workers, with local Discord/LLM doubles."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from airi.adapters.state_store import StateStore
from airi.coordinator.policy import ParticipationPolicy
from airi.coordinator.server import create_app
from airi.coordinator.store import ChannelCoordinator
from airi.coordinator.worker import API, DiscordWorker, Superseded
from airi.discord_bot.context import BotContext
from airi.services.conversation import ConversationService
from airi.services.persistence import StatePersistence
from airi.services.turn_journal import TurnJournal
from airi.testing import FakeLLM, llm_json, make_state


def test_http_auth_and_event_validation(tmp_path):
    async def scenario():
        store = ChannelCoordinator(
            tmp_path / "api.sqlite3", {"airi": "10", "luna": "20"}, channel_id="7"
        )
        client = TestClient(TestServer(create_app(store, {"airi": "a" * 24, "luna": "b" * 24})))
        await client.start_server()
        try:
            assert (await client.get("/readyz")).status == 200
            assert (await client.post("/events", json={})).status == 401
            headers = {"Authorization": "Bearer " + "a" * 24}
            assert (await client.post("/events", json={}, headers=headers)).status == 400
            response = await client.post(
                "/workers/register", json={"discord_id": "20"}, headers=headers
            )
            assert response.status == 409
            assert (await client.post("/jobs/missing/ready", headers=headers)).status == 409
        finally:
            await client.close()
            store.close()

    asyncio.run(scenario())


class Channel:
    id = 7

    def __init__(self):
        self.messages = {}
        self.author = None
        self.counter = 1000

    @asynccontextmanager
    async def typing(self):
        yield

    async def fetch_message(self, identifier):
        return self.messages[identifier]

    async def send(self, content=None, **kwargs):
        self.counter += 1
        message = SimpleNamespace(
            id=self.counter,
            channel=self,
            author=self.author,
            content=content or "",
            embeds=[kwargs["embed"]] if kwargs.get("embed") else [],
            mentions=[],
            reference=None,
            webhook_id=None,
            created_at=datetime.now(timezone.utc),
        )
        self.messages[message.id] = message
        return message

    async def history(self, limit):
        for message in list(self.messages.values())[-limit:][::-1]:
            yield message


def test_two_workers_real_pipeline_and_peer_state_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRI_CONVERSATION_REVIEW", "0")

    async def no_gif(*args, **kwargs):
        pass

    monkeypatch.setattr("airi.discord_bot.turn.send_gif_bytes", no_gif)

    async def scenario():
        store = ChannelCoordinator(
            tmp_path / "server.sqlite3",
            {"airi": "10", "luna": "20"},
            channel_id="7",
            debounce=0,
            reply_delay=0,
            policy=ParticipationPolicy(max_interventions=2),
        )
        server = TestServer(create_app(store, {"airi": "a" * 24, "luna": "b" * 24}))
        await server.start_server()
        channel = Channel()
        user = SimpleNamespace(id=42, display_name="David", bot=False)
        source = SimpleNamespace(
            id=100,
            author=user,
            channel=channel,
            content="Hola a los dos",
            mentions=[],
            reference=None,
            embeds=[],
            webhook_id=None,
        )
        channel.messages[100] = source
        workers, states = [], []
        async with aiohttp.ClientSession() as session:
            try:
                for bot, uid, token in [("airi", 10, "a"), ("luna", 20, "b")]:
                    monkeypatch.setenv("AIRI_BOT_ID", bot)
                    monkeypatch.setenv("AIRI_PERSONA_FILE", f"config/{bot}.json")
                    monkeypatch.setenv("COORDINATOR_BOTS", json.dumps(store.bots))
                    monkeypatch.setenv("AIRI_DATA_DIR", str(tmp_path / bot))
                    state, _ = make_state()
                    persistence = StatePersistence(StateStore(tmp_path / bot))
                    persistence.bind(state)
                    persistence.save()
                    llm = FakeLLM(
                        [llm_json("Hola David", affinity_delta=2, affinity_event="alegría")]
                    )
                    service = ConversationService(llm=llm, state=state)
                    ctx = BotContext(
                        channel_id=7,
                        state=state,
                        persistence=persistence,
                        turn_journal=TurnJournal(state, persistence=persistence),
                        commit_lock=asyncio.Lock(),
                        llm_health_check=False,
                        build_service=lambda *args, service=service: service,
                    )
                    client = SimpleNamespace(
                        user=SimpleNamespace(id=uid, display_name=bot, bot=True),
                        get_channel=lambda _id: channel,
                        is_ready=lambda: True,
                    )
                    worker = DiscordWorker(client, lambda _ch, ctx=ctx: ctx, None, 7)
                    worker.api = API(session, str(server.make_url("")).rstrip("/"), token * 24)
                    await worker.status()
                    workers.append(worker)
                    states.append(state)
                # Both clients observe the same event, but only one job exists.
                for worker in workers:
                    await worker.observe(source)
                first = (await workers[0].api.post("/jobs/claim"))["job"]
                assert first["bot"] == "airi"
                decision_llm = FakeLLM(['{"participate":true,"reason_code":"invitation"}'])
                monkeypatch.setattr(
                    "airi.adapters.http_llm.build_llm", lambda *a, **kw: decision_llm
                )
                await workers[0].execute(first)
                assert store.get_job(first["id"], "airi")["status"] == "decided"
                first = (await workers[0].api.post("/jobs/claim"))["job"]
                monkeypatch.setenv("AIRI_PERSONA_FILE", "config/airi.json")
                channel.author = workers[0].client.user
                await workers[0].execute(first)
                assert store.get_job(first["id"], "airi")["status"] == "published"
                assert states[0].affinity["42"]["points"] == 2
                # Peer response uses only a public context and a dedicated LLM path.
                peer_llm = FakeLLM(
                    [
                        '{"participate":true,"reason_code":"sibling"}',
                        '{"reply":"También me alegra verte, David."}',
                    ]
                )
                monkeypatch.setattr("airi.adapters.http_llm.build_llm", lambda *a, **kw: peer_llm)
                monkeypatch.setenv("AIRI_PERSONA_FILE", "config/luna.json")
                second = (await workers[1].api.post("/jobs/claim"))["job"]
                await workers[1].execute(second)
                second = (await workers[1].api.post("/jobs/claim"))["job"]
                channel.author = workers[1].client.user
                await workers[1].execute(second)
                assert store.get_job(second["id"], "luna")["status"] == "published"
                assert states[1].affinity == {}
                assert states[1].memories == {}
                assert states[1].dates == {}
                assert "Luna" in peer_llm.last_system_prompt
                assert "Eres hermana de Airi" in peer_llm.last_system_prompt
                assert '"discord_user_id": "10"' in peer_llm.last_system_prompt
                assert '"discord_user_id": "20"' in peer_llm.last_system_prompt
                assert not store.db.execute("SELECT 1 FROM jobs WHERE status='queued'").fetchone()

                commands = []

                async def handle_command(ctx, message):
                    commands.append(message.content)
                    await message.reply("Regalo recibido")

                workers[1].registry = SimpleNamespace(match=lambda content: handle_command)
                channel.counter = 2000
                command = SimpleNamespace(
                    id=2000,
                    author=user,
                    channel=channel,
                    content="<@20> !regalo <@42>",
                    mentions=[workers[1].client.user, user],
                    reference=None,
                    embeds=[],
                    webhook_id=None,
                )
                channel.messages[2000] = command
                for worker in workers:
                    await worker.observe(command)
                command_job = (await workers[1].api.post("/jobs/claim"))["job"]
                await workers[1].execute(command_job)
                assert commands == ["!regalo <@42>"]
                assert not store.db.execute("SELECT 1 FROM jobs WHERE status='queued'").fetchone()
            finally:
                for worker in workers:
                    await worker.close()
                await server.close()
                store.close()

    asyncio.run(scenario())


def test_authorization_rejection_prevents_domain_commit(tmp_path):
    from airi.services.conversation import TurnContext
    from tests.unit.test_turn_coordinator import DAVID, make_harness

    async def scenario():
        state, _, _, _, coordinator, _ = make_harness(tmp_path)
        original = dict(state.affinity)
        published = []

        async def cancelled():
            raise Superseded()

        async def publisher(result):
            published.append(result)

        try:
            await coordinator.execute(
                channel_id=7,
                user=DAVID,
                messages=[(DAVID, "hola")],
                message_ids=["100"],
                context=TurnContext(channel_id=7),
                publisher=publisher,
                before_commit=cancelled,
            )
        except Superseded:
            pass
        else:
            raise AssertionError("Superseded turn was accepted")
        assert state.affinity == original
        assert not published

    asyncio.run(scenario())
