import asyncio
import json
import logging

import pytest

from airi.coordinator.worker import DiscordWorker
from airi.persona import load_persona
from airi.ports.llm import LLMMeta, PayloadCaptureResult
from airi.testing import FakeLLM


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def worker():
    # No client, channel or private state is necessary for a public decision.
    value = object.__new__(DiscordWorker)
    value.persona = load_persona("config/luna.json")
    value.bot = "luna"
    value.bots = {"airi": "10", "luna": "20"}
    return value


def job():
    return {
        "id": "decision-1",
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
    assert "menciona explícitamente a ambos" in llm.last_system_prompt
    payload = json.loads(llm.calls[0]["messages"][1]["content"])
    assert payload["history"] == job()["history"]
    assert "memories" not in payload
    assert llm.calls[0]["quick_turn"] is True
    context = llm.calls[0]["call_context"]
    assert context.correlation_id == job()["id"]
    assert (context.purpose, context.call_index) == ("peer_decision", 1)


def test_decision_context_is_supplied_even_for_invalid_reply(monkeypatch):
    llm = FakeLLM(["not json"])
    monkeypatch.setattr("airi.adapters.http_llm.build_llm", lambda *args, **kwargs: llm)
    assert asyncio.run(worker().participation_decision(job())) == {
        "participate": False, "reason_code": "error",
    }
    assert llm.calls[0]["call_context"].correlation_id == job()["id"]


def test_decision_capture_failure_warns_without_payload(monkeypatch, caplog):
    llm = FakeLLM(
        ['{"participate":false,"reason_code":"humans_talking"}'],
        metas=[LLMMeta(response_capture=PayloadCaptureResult(status="failed", error="OSError"))],
    )
    monkeypatch.setattr("airi.adapters.http_llm.build_llm", lambda *args, **kwargs: llm)
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(worker().participation_decision(job()))
    assert result == {"participate": False, "reason_code": "humans_talking"}
    assert "Decision capture failed" in caplog.text
    assert job()["id"] in caplog.text
    assert "¿Qué opinas, Luna?" not in caplog.text


def test_worker_info_logs_visible_without_changing_root_level(capsys):
    from airi.coordinator import worker as module

    root = logging.getLogger()
    level = root.level
    original_level, original_propagate = module.log.level, module.log.propagate
    before = list(module.log.handlers)
    try:
        module.install_worker_logging()
        module.install_worker_logging()
        assert root.level == level
        assert module.log.getEffectiveLevel() <= logging.INFO
        assert module.log.propagate is False
        assert len(module.log.handlers) == len(before) + 1
        module.log.info("Coordinated job: bot=luna job=decision-1 kind=decision")
        assert "job=decision-1" in capsys.readouterr().err
    finally:
        for handler in module.log.handlers[:]:
            if handler not in before:
                module.log.removeHandler(handler)
                handler.close()
        module.log.setLevel(original_level)
        module.log.propagate = original_propagate


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


def test_decision_logs_job_and_reason_without_content(monkeypatch, caplog):
    llm = FakeLLM(['{"participate":false,"reason_code":"humans_talking"}'])
    monkeypatch.setattr("airi.adapters.http_llm.build_llm", lambda *args, **kwargs: llm)

    with caplog.at_level(logging.INFO):
        decision = asyncio.run(worker().participation_decision(job()))

    assert decision == {"participate": False, "reason_code": "humans_talking"}
    assert "Participation decision" in caplog.text
    assert job()["id"] in caplog.text
    assert "humans_talking" in caplog.text
    assert "¿Qué opinas, Luna?" not in caplog.text


def test_proactive_generation_needs_no_synthetic_user_or_private_state(monkeypatch):
    llm = FakeLLM(['{"reply":"Airi, ¿te apetece hablar de nuestras estrellas?"}'])
    monkeypatch.setattr("airi.adapters.http_llm.build_llm", lambda *args, **kwargs: llm)

    class Channel:
        def __init__(self):
            self.sent = []

        def typing(self):
            return _Typing()

        async def send(self, text):
            self.sent.append(text)

    channel = Channel()
    asyncio.run(
        worker().peer_reply(
            channel, {"id": "proactive-1", "kind": "proactive", "history": []}
        )
    )
    assert channel.sent == ["Airi, ¿te apetece hablar de nuestras estrellas?"]
    assert "iniciar una charla" in llm.last_system_prompt
    assert "No reclames atención" in llm.last_system_prompt
