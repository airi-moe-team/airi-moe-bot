import asyncio
import json

from airi.adapters.http_llm import HttpLlmClient
from airi.observability.llm_payload_capture import LocalLlmPayloadCapture, load_llm_payload
from airi.services.conversation import ConversationService, TurnContext
from airi.testing import FakeUser, llm_json, make_state


class _Response:
    status = 200

    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass

    async def json(self):
        return {"choices": [{"message": {
            "content": self.content,
            "reasoning_content": "razonamiento privado de prueba",
        }}]}


class _PostContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return _Response(llm_json("Respuesta de integración"))

    async def __aexit__(self, *exc_info):
        return False


class _Session:
    def post(self, url, *, json, **kwargs):
        self.payload = json
        self.url = url
        self.kwargs = kwargs
        return _PostContext(self)


def test_conversation_trace_points_to_exact_local_request_body(monkeypatch, tmp_path):
    monkeypatch.setenv("AIRI_CONVERSATION_REVIEW", "0")
    monkeypatch.setenv("AIRI_WEB_SEARCH", "0")
    session = _Session()
    llm = HttpLlmClient(
        "http://localhost:7000",
        session,
        payload_capture=LocalLlmPayloadCapture(tmp_path),
    )
    state, _ = make_state()
    user = FakeUser(42, "Kokoda")
    service = ConversationService(llm=llm, state=state, clock=lambda: 1_000_000)

    result = asyncio.run(service.run_turn(
        user,
        [(user, "mensaje sintético")],
        TurnContext(correlation_id="trace-e2e"),
    ))

    call = result.trace.llm_calls[0]
    capture = call["payload_capture"]
    assert call["model"] == llm.model
    assert call["provider"] == llm.provider
    stored_payload = load_llm_payload(
        tmp_path / capture["artifact_ref"],
        correlation_id="trace-e2e",
        call_index=1,
        sha256=capture["sha256"],
    )
    assert stored_payload == session.payload
    assert stored_payload["model"] == llm.model
    assert "Authorization" not in json.dumps(stored_payload)
    serialized_trace = json.dumps(result.trace.to_dict())
    assert capture["artifact_ref"] in serialized_trace
    assert '"payload":' not in serialized_trace
    response_capture = call["response_capture"]
    from airi.observability.llm_payload_capture import load_llm_response
    response = load_llm_response(
        tmp_path / response_capture["artifact_ref"],
        correlation_id="trace-e2e", call_index=1,
        sha256=response_capture["sha256"],
    )
    assert response["content"] == result.trace.raw_llm
    assert response["reasoning_content"] == "razonamiento privado de prueba"
    assert "raw_llm" not in result.trace.to_dict()
    assert "razonamiento privado de prueba" not in serialized_trace
