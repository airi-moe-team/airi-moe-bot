import asyncio
import json

import pytest

from airi.coordinator.worker import DiscordWorker
from airi.persona import load_persona
from airi.testing import FakeLLM


def worker():
    # No client, channel or private state is necessary for a public decision.
    value = object.__new__(DiscordWorker)
    value.persona = load_persona("config/luna.json")
    value.bot = "luna"
    value.bots = {"airi": "10", "luna": "20"}
    return value


def job():
    return {
        "target_kind": "peer",
        "history": [
            {
                "author_id": "10",
                "name": "Airi",
                "kind": "bot",
                "content": "¿Qué opinas, Luna?",
            }
        ],
    }


def test_decision_uses_own_model_and_public_sibling_context(monkeypatch):
    llm = FakeLLM(['{"participate":true,"reason_code":"sibling"}'])
    monkeypatch.setattr("airi.adapters.http_llm.build_llm", lambda *args, **kwargs: llm)
    decision = asyncio.run(worker().participation_decision(job()))
    assert decision == {"participate": True, "reason_code": "sibling"}
    assert len(llm.calls) == 1
    assert "Luna" in llm.last_system_prompt
    assert "Airi es la hermana mayor" in llm.last_system_prompt
    payload = json.loads(llm.calls[0]["messages"][1]["content"])
    assert payload["history"] == job()["history"]
    assert "memories" not in payload
    assert llm.calls[0]["quick_turn"] is True


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",
        '{"participate":"true","reason_code":"sibling"}',
        '{"participate":true,"reason_code":"invented"}',
        '{"participate":true,"reason_code":"error"}',
    ],
)
def test_invalid_decision_is_silence_without_retry(monkeypatch, raw):
    llm = FakeLLM([raw])
    monkeypatch.setattr("airi.adapters.http_llm.build_llm", lambda *args, **kwargs: llm)
    assert asyncio.run(worker().participation_decision(job())) == {
        "participate": False,
        "reason_code": "error",
    }
    assert len(llm.calls) == 1


def test_timeout_is_silence_without_retry(monkeypatch):
    calls = []

    class SlowModel:
        async def chat_with_meta(self, *args, **kwargs):
            calls.append(1)
            raise asyncio.TimeoutError()

    monkeypatch.setattr("airi.adapters.http_llm.build_llm", lambda *args, **kwargs: SlowModel())
    assert asyncio.run(worker().participation_decision(job())) == {
        "participate": False,
        "reason_code": "error",
    }
    assert len(calls) == 1


def test_proactive_generation_needs_no_synthetic_user_or_private_state(monkeypatch):
    llm = FakeLLM(['{"reply":"Airi, ¿te apetece hablar de nuestras estrellas?"}'])
    monkeypatch.setattr("airi.adapters.http_llm.build_llm", lambda *args, **kwargs: llm)
    sent = []

    class Channel:
        async def send(self, text):
            sent.append(text)

    asyncio.run(worker().peer_reply(Channel(), {"kind": "proactive", "history": []}))
    assert sent == ["Airi, ¿te apetece hablar de nuestras estrellas?"]
    assert "iniciar una charla" in llm.last_system_prompt
    assert "No reclames atención" in llm.last_system_prompt
