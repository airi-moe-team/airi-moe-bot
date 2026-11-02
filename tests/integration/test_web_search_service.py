import asyncio

from airi.domain.web_tool import WEB_SEARCH_TOOL
from airi.services.web_search import WebSearchService, _is_acknowledgment_only
from airi.testing import FakeLLM, FakeNotifier, FakeSearch


def run(coro):
    return asyncio.run(coro)


def _tool_call(query="precio bitcoin hoy", motivo="me entró curiosidad"):
    return [{
        "id": "call-1",
        "name": "buscar_web",
        "arguments": {"query": query, "motivo": motivo},
    }]


def test_acknowledgment_classifier_collapses_vowels_without_corrupting_words():
    assert _is_acknowledgment_only(
        "siiiiiiiiiiiiiii bim bom otra respuesta correcta  bieeeen"
    )
    assert _is_acknowledgment_only("sii your name felicidades ganaste")
    assert _is_acknowledgment_only("¡Felicidades! Esa respuesta era correcta.")
    assert not _is_acknowledgment_only("¡Sí, acertaste! ¿Quién escribió One Piece?")
    assert not _is_acknowledgment_only(
        "¡Sí, acertaste! La siguiente frase es: '¿Quién soy?'"
    )


def test_acknowledgment_with_explicit_search_request_is_not_suppressed():
    assert not _is_acknowledgment_only("¡Felicidades! Busca quién escribió One Piece.")


def test_acknowledgment_with_factual_doubt_is_not_suppressed():
    assert not _is_acknowledgment_only(
        "¡Felicidades, pero creo que esa respuesta es falsa!"
    )
    assert not _is_acknowledgment_only("Bien, no estoy segura de que sea verdad.")


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


def test_confirming_correct_guess_does_not_search_even_with_search_tool_call():
    llm = FakeLLM(tool_calls=[_tool_call(
        "One Piece frase de Luffy", "quiero volver a comprobar la respuesta anterior"
    )])
    search = FakeSearch(result="no debe buscarse")
    notifier = FakeNotifier()
    service = WebSearchService(llm=llm, search=search, notifier=notifier)

    outcome = run(service.run(
        current_text="siiiiiiiiiiiiiii bim bom otra respuesta correcta bieeeen",
        context="Airi respondió One Piece; el usuario confirmó que acertó.",
    ))

    assert outcome.requested is False
    assert outcome.finish_reason == "acknowledgment_suppressed"
    assert llm.decision_calls == []
    assert search.queries == []
    assert notifier.sent == []


def test_confirmation_with_explicit_followup_question_still_allows_search():
    llm = FakeLLM(tool_calls=[_tool_call("autor de One Piece")])
    search = FakeSearch(result="Eiichiro Oda")
    service = WebSearchService(llm=llm, search=search)

    outcome = run(service.run(
        current_text="¡Sí, acertaste! ¿Quién escribió One Piece?",
        context="Estábamos jugando a adivinar animes.",
    ))

    assert outcome.requested is True
    assert search.queries == ["autor de One Piece"]


def test_confirmation_does_not_hide_a_new_item_in_an_active_game():
    llm = FakeLLM(tool_calls=[_tool_call("origen de la frase", "nueva pista del juego")])
    search = FakeSearch(result="respuesta encontrada")
    service = WebSearchService(llm=llm, search=search)

    outcome = run(service.run(
        current_text="¡Ganaste! La siguiente frase: 'Si puedo volver a verte, te encontraré'.",
        context="Estamos jugando a identificar frases de anime. Airi acertó la anterior.",
    ))

    assert outcome.requested is True
    assert search.queries == ["origen de la frase"]


def test_acknowledgment_with_doubt_allows_model_to_verify_claim():
    llm = FakeLLM(tool_calls=[_tool_call(
        "verificar si la respuesta anterior es falsa", "el usuario expresa duda factual"
    )])
    search = FakeSearch(result="La fuente confirma el dato")
    service = WebSearchService(llm=llm, search=search)

    outcome = run(service.run(
        current_text="¡Felicidades, pero creo que esa respuesta es falsa!",
        context="Airi acaba de identificar una frase como de Your Name.",
    ))

    assert outcome.requested is True
    assert search.queries == ["verificar si la respuesta anterior es falsa"]


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
