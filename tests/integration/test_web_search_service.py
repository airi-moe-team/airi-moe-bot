import asyncio

from airi.domain.web_tool import WEB_SEARCH_TOOL
from airi.services.web_search import WebSearchService
from airi.testing import FakeLLM, FakeNotifier, FakeSearch


def run(coro):
    return asyncio.run(coro)


def _tool_call(query="precio bitcoin hoy", motivo="me entró curiosidad"):
    return [{
        "id": "call-1",
        "name": "buscar_web",
        "arguments": {"query": query, "motivo": motivo},
    }]


def test_model_tool_call_triggers_one_search_and_produces_prompt_notes():
    llm = FakeLLM(tool_calls=[_tool_call()])
    search = FakeSearch(result="Bitcoin ronda los 30 mil euros.")
    notifier = FakeNotifier()
    service = WebSearchService(llm=llm, search=search, notifier=notifier)

    outcome = run(service.run(current_text="¿A cuánto está Bitcoin?", context="Hablábamos de BTC"))

    assert outcome.requested is True
    assert search.queries == ["precio bitcoin hoy"]
    assert "30 mil euros" in outcome.prompt_block
    assert "me entró curiosidad" in outcome.prompt_block
    assert len(notifier.sent) == 1
    assert llm.decision_calls[0]["tools"] == [WEB_SEARCH_TOOL]
    assert llm.decision_calls[0]["tool_choice"] == "auto"
    assert llm.decision_calls[0]["schema"] is None


def test_no_tool_call_means_no_search_and_no_notice():
    llm = FakeLLM(replies=["respuesta final"])
    search = FakeSearch(result="no debe usarse")
    notifier = FakeNotifier()
    service = WebSearchService(llm=llm, search=search, notifier=notifier)

    outcome = run(service.run(current_text="¿Te gusta el helado?"))

    assert outcome.requested is False
    assert outcome.prompt_block is None
    assert search.queries == []
    assert notifier.sent == []
    assert llm.replies == ["respuesta final"]


def test_failed_search_returns_control_context_not_reply_template():
    llm = FakeLLM(tool_calls=[_tool_call()])
    service = WebSearchService(
        llm=llm, search=FakeSearch(result=None), notifier=FakeNotifier()
    )

    outcome = run(service.run(current_text="¿Precio actual de BTC?"))

    assert outcome.failed is True
    assert outcome.prompt_block
    assert "no devolvió notas útiles" in outcome.prompt_block
    assert "No he encontrado información fiable" not in outcome.prompt_block
