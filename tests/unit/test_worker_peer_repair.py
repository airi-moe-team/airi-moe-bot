import asyncio
import json
import logging

import pytest

from airi.coordinator.worker import DiscordWorker
from airi.persona import load_persona
from airi.ports.llm import LLMMeta, PayloadCaptureResult
from airi.testing import FakeLLM


def worker():
    value = object.__new__(DiscordWorker)
    value.persona = load_persona("config/luna.json")
    value.bot = "luna"
    value.bots = {"airi": "10", "luna": "20"}
    return value


def job():
    return {
        "id": "job-peer-1",
        "kind": "peer",
        "history": [
            {
                "author_id": "10",
                "name": "Airi",
                "kind": "bot",
                "content": "¿Qué opinas, Luna?",
            }
        ],
    }


class Typing:
    def __init__(self, channel):
        self.channel = channel

    async def __aenter__(self):
        self.channel.typing_entries += 1
        self.channel.typing_depth += 1
        return self

    async def __aexit__(self, *exc_info):
        self.channel.typing_depth -= 1
        self.channel.typing_exits += 1
        return False


class Channel:
    def __init__(self):
        self.sent = []
        self.typing_entries = 0
        self.typing_exits = 0
        self.typing_depth = 0

    def typing(self):
        return Typing(self)

    async def send(self, text):
        self.sent.append(text)


def run_with(monkeypatch, llm, channel):
    monkeypatch.setattr("airi.adapters.http_llm.build_llm", lambda *args, **kwargs: llm)
    asyncio.run(worker().peer_reply(channel, job()))
    return llm, channel


def run(monkeypatch, replies):
    return run_with(monkeypatch, FakeLLM(replies), Channel())


class RecordingLLM(FakeLLM):
    def __init__(self, replies, channel):
        super().__init__(replies)
        self.channel = channel
        self.typing_seen = []

    async def chat_with_meta(self, messages, **kwargs):
        self.typing_seen.append(self.channel.typing_depth)
        return await super().chat_with_meta(messages, **kwargs)


def test_valid_reply_keeps_single_call(monkeypatch):
    llm, channel = run(monkeypatch, ['{"reply":"Hola Airi"}'])
    assert channel.sent == ["Hola Airi"]
    assert len(llm.calls) == 1
    assert llm.calls[0]["schema"]["required"] == ["reply"]


def test_invalid_primary_is_repaired_with_same_context(monkeypatch):
    llm, channel = run(monkeypatch, ["not json", '{"reply":"Hola Airi"}'])
    assert channel.sent == ["Hola Airi"]
    assert len(llm.calls) == 2
    assert llm.calls[0]["messages"][0] == llm.calls[1]["messages"][0]
    repair = llm.calls[1]["messages"]
    assert repair[-2] == {"role": "assistant", "content": "not json"}
    assert repair[-1]["role"] == "user"
    assert "formato" in repair[-1]["content"].lower()
    assert llm.calls[1]["schema"]["required"] == ["reply"]


@pytest.mark.parametrize("raw", ['{"reply":""}', '{"reply":"   "}'])
def test_empty_reply_is_valid_silence_without_repair(monkeypatch, raw):
    llm, channel = run(monkeypatch, [raw])
    assert channel.sent == []
    assert len(llm.calls) == 1


def test_empty_repaired_reply_is_valid_silence(monkeypatch):
    llm, channel = run(monkeypatch, ["not json", '{"reply":""}'])
    assert channel.sent == []
    assert len(llm.calls) == 2


def test_exhausted_repair_fails_without_publishing(monkeypatch):
    llm = FakeLLM(["not json", "still not json"])
    monkeypatch.setattr("airi.adapters.http_llm.build_llm", lambda *args, **kwargs: llm)
    channel = Channel()
    with pytest.raises(ValueError, match="Invalid peer response after repair"):
        asyncio.run(worker().peer_reply(channel, job()))
    assert channel.sent == []
    assert len(llm.calls) == 2


def test_transport_error_is_not_repaired(monkeypatch):
    calls = []

    class BrokenModel:
        async def chat_with_meta(self, *args, **kwargs):
            calls.append(1)
            raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "airi.adapters.http_llm.build_llm", lambda *args, **kwargs: BrokenModel()
    )
    with pytest.raises(RuntimeError, match="connection refused"):
        asyncio.run(worker().peer_reply(Channel(), job()))
    assert len(calls) == 1


def test_history_is_preserved_in_repair(monkeypatch):
    llm, _ = run(monkeypatch, ["not json", '{"reply":"Hola"}'])
    primary_history = json.loads(llm.calls[0]["messages"][1]["content"])
    repair_history = json.loads(llm.calls[1]["messages"][1]["content"])
    assert repair_history == primary_history == job()["history"]


def test_typing_is_active_during_primary_and_repair(monkeypatch):
    channel = Channel()
    llm = RecordingLLM(["not json", '{"reply":"Hola Airi"}'], channel)

    run_with(monkeypatch, llm, channel)

    assert llm.typing_seen == [1, 1]
    assert channel.typing_entries == 1
    assert channel.typing_exits == 1
    assert channel.typing_depth == 0
    assert channel.sent == ["Hola Airi"]


def test_typing_is_closed_on_valid_silence(monkeypatch):
    channel = Channel()
    llm = RecordingLLM(['{"reply":""}'], channel)

    run_with(monkeypatch, llm, channel)

    assert llm.typing_seen == [1]
    assert channel.typing_depth == 0
    assert channel.typing_exits == 1
    assert channel.sent == []


def test_typing_is_closed_when_model_fails(monkeypatch):
    channel = Channel()
    observed = []

    class BrokenModel:
        async def chat_with_meta(self, *args, **kwargs):
            observed.append(channel.typing_depth)
            raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "airi.adapters.http_llm.build_llm", lambda *args, **kwargs: BrokenModel()
    )
    with pytest.raises(RuntimeError, match="connection refused"):
        asyncio.run(worker().peer_reply(channel, job()))

    assert observed == [1]
    assert channel.typing_depth == 0
    assert channel.typing_exits == 1


def test_typing_is_closed_on_cancellation(monkeypatch):
    channel = Channel()

    class CancelledModel:
        async def chat_with_meta(self, *args, **kwargs):
            raise asyncio.CancelledError()

    monkeypatch.setattr(
        "airi.adapters.http_llm.build_llm", lambda *args, **kwargs: CancelledModel()
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker().peer_reply(channel, job()))

    assert channel.typing_depth == 0
    assert channel.typing_exits == 1
    assert channel.sent == []


def test_peer_calls_share_job_id_with_distinct_purposes(monkeypatch):
    llm, _ = run(monkeypatch, ["not json", '{"reply":"Hola"}'])

    primary = llm.calls[0]["call_context"]
    repair = llm.calls[1]["call_context"]
    assert primary.correlation_id == repair.correlation_id == job()["id"]
    assert (primary.purpose, primary.call_index) == ("peer_primary", 1)
    assert (repair.purpose, repair.call_index) == ("peer_parse_repair", 2)


def test_capture_failure_warns_without_leaking_content(monkeypatch, caplog):
    private_reply = "contenido privado de prueba"
    meta = LLMMeta(
        response_capture=PayloadCaptureResult(status="failed", error="OSError")
    )
    llm = FakeLLM([json.dumps({"reply": private_reply})], metas=[meta])

    with caplog.at_level(logging.WARNING):
        run_with(monkeypatch, llm, Channel())

    assert "Peer response capture failed" in caplog.text
    assert job()["id"] in caplog.text
    assert "peer_primary" in caplog.text
    assert private_reply not in caplog.text


def test_peer_generation_logs_metadata_without_content(monkeypatch, caplog):
    private_reply = "respuesta privada de Luna"

    with caplog.at_level(logging.INFO):
        run(monkeypatch, [json.dumps({"reply": private_reply})])

    assert "Peer generation started" in caplog.text
    assert "Peer generation finished" in caplog.text
    assert job()["id"] in caplog.text
    assert private_reply not in caplog.text
