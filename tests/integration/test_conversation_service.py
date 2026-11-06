"""Tests de integración de ConversationService con fakes (sin red ni Discord)."""

import asyncio
import json

import pytest

from airi.domain.constants import LLM_SHORT_MAX_TOKENS
from airi.domain.dates import new_date_session
from airi.ports.llm import LLMMeta
from airi.services.conversation import (
    ConversationService,
    TurnContext,
)
from airi.testing import FakeGif, FakeLLM, FakeNotifier, FakeSearch, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")


def make_service(llm, state, *, search=None, gifs=None, notifier=None,
                 date_delta_max=5):
    return ConversationService(
        llm=llm,
        state=state,
        search=search,
        gifs=gifs,
        notifier=notifier,
        clock=lambda: NOW,
        date_delta_max=date_delta_max,
    )


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Turno básico
# ---------------------------------------------------------------------------


def test_turn_replies_and_applies_affinity():
    state, counters = make_state()
    llm = FakeLLM(replies=[llm_json("¡Qué ramen tan bueno!", affinity_delta=2,
                                     affinity_event="me hizo reír")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "te traigo ramen")], TurnContext()))

    assert result.reply == "¡Qué ramen tan bueno!"
    assert result.affinity_delta == 2
    assert result.affinity_applied == 2
    assert state.entry_points(42) == 2
    assert counters["affinity"] == 1
    # Usuario registrado e historial guardado.
    assert state.users["42"]["name"] == "David"
    assert counters["users"] == 1
    # El historial de asistente se guarda SIEMPRE como JSON (formato de salida).
    entry = state.histories[0][-1]
    assert entry["role"] == "assistant"
    payload = json.loads(entry["content"])
    assert payload["reply"] == result.reply
    assert payload["affinity_delta"] == 2


def test_turn_invalid_json_is_repaired_instead_of_publishing_raw_text():
    state, _ = make_state()
    llm = FakeLLM(
        replies=["esto no es json pero tiene reply: hola", llm_json("hola, ya estoy")]
    )
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.reply == "hola, ya estoy"
    assert result.affinity_applied == 0  # sin evento, el candado fuerza 0


def test_turn_delta_without_event_is_zeroed():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("hola", affinity_delta=5, affinity_event="none")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.affinity_delta == 0
    assert state.entry_points(42) == 0


def test_turn_repeated_answer_is_published():
    """Sin filtro de duplicados, una respuesta repetida se envía igual."""
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "David: hola"},
        {"role": "assistant", "content": "Ya te dije hola antes"},
    ]
    llm = FakeLLM(replies=[llm_json("Ya te dije hola antes")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.skipped is False
    assert result.reply == "Ya te dije hola antes"
    # Historial previo + mensaje nuevo del usuario + respuesta publicada.
    assert len(state.histories[0]) == 4
    assert state.histories[0][-2]["role"] == "user"
    assert json.loads(state.histories[0][-1]["content"])["reply"] == result.reply


# ---------------------------------------------------------------------------
# Salida estructurada estricta (json_schema) con fallback
# ---------------------------------------------------------------------------


def test_turn_uses_strict_json_schema():
    """El turno principal pide JSON estricto al servidor (gramática)."""
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("hola")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert llm.calls[-1]["strict_schema"] is True
    assert llm.calls[-1]["schema"] is not None


def test_short_turn_uses_compact_contract_and_output_cap():
    """Un mensaje corto evita el contrato largo y limita la salida."""
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("¡Hola!")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    prompt = llm.last_system_prompt
    assert "TURNO BREVE" in prompt
    assert "FORMATO DE SALIDA OBLIGATORIO" not in prompt
    assert llm.calls[-1]["max_tokens"] == LLM_SHORT_MAX_TOKENS
    assert llm.calls[-1]["strict_schema"] is True
    # El servicio marca el turno rápido; `auto` asigna low sin apagar reasoning.
    assert llm.calls[-1]["quick_turn"] is True
    assert llm.calls[-1]["reasoning_budget_tokens"] is None
    # El historial compartido conserva etiquetas, con su explicación breve.
    assert "=== ETIQUETAS DE IDENTIDAD Y CONTEXTO ===" in prompt
    assert "Trata a cada persona de forma independiente" in prompt


def test_long_turn_uses_full_contract():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("Claro")])
    svc = make_service(llm, state, notifier=FakeNotifier())
    message = "explícame con mucho detalle cómo funciona un motor de combustión interna"

    run(svc.run_turn(DAVID, [(DAVID, message)], TurnContext()))

    prompt = llm.last_system_prompt
    assert "FORMATO DE SALIDA OBLIGATORIO" in prompt
    assert "TURNO BREVE" not in prompt
    assert llm.calls[-1]["max_tokens"] is None
    assert llm.calls[-1]["quick_turn"] is False


def test_prompt_variant_changes_only_system_message_not_quick_contract():
    message = "explícame con mucho detalle cómo funciona un motor de combustión interna"
    llms = [FakeLLM(replies=[llm_json("Claro")]) for _ in range(2)]
    contexts = [
        TurnContext(system_prompt_variant="current"),
        TurnContext(system_prompt_variant="compact_candidate"),
    ]
    for llm, context in zip(llms, contexts):
        state, _ = make_state()
        svc = make_service(llm, state, notifier=FakeNotifier())
        run(svc.run_turn(DAVID, [(DAVID, message)], context))

    current_call, candidate_call = (llm.calls[-1] for llm in llms)
    assert current_call["messages"][0]["content"] != candidate_call["messages"][0]["content"]
    assert current_call["messages"][1:] == candidate_call["messages"][1:]
    for key in ("schema", "max_tokens", "reasoning_budget_tokens", "quick_turn", "strict_schema"):
        assert current_call[key] == candidate_call[key]
    assert current_call["quick_turn"] is False
    assert current_call["max_tokens"] is None
    assert all(
        call["messages"][1:] == llms[0].calls[0]["messages"][1:]
        for llm in llms
        for call in llm.calls
    )


def test_streaming_is_opt_in_and_records_client_and_server_timings():
    state, _ = make_state()
    llm = FakeLLM(
        replies=[llm_json("Respuesta")],
        metas=[
            LLMMeta(
                finish_reason="stop",
                usage={"prompt_tokens": 12, "completion_tokens": 3},
                ttft_ms=42,
                first_content_ms=58,
                server_timings={"prompt_ms": 20.0, "predicted_ms": 10.0},
                reasoning_present=True,
                reasoning_tokens=7,
            )
        ],
    )
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(
        svc.run_turn(
            DAVID,
            [(DAVID, "explícame detalladamente cómo funciona un motor")],
            TurnContext(stream_llm=True),
        )
    )

    assert llm.calls[0]["stream"] is True
    assert result.trace.llm_ttft_ms == 42
    assert result.trace.llm_first_content_ms == 58
    assert result.trace.llm_server_timings == {"prompt_ms": 20.0, "predicted_ms": 10.0}
    assert result.trace.llm_reasoning_present is True
    assert result.trace.llm_reasoning_tokens == 7


def test_normal_turn_does_not_enable_streaming_or_add_ttft():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("Respuesta")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(
        svc.run_turn(DAVID, [(DAVID, "explícame detalladamente un motor")], TurnContext())
    )

    assert "stream" not in llm.calls[0]
    assert result.trace.llm_ttft_ms is None


def test_short_memory_question_uses_full_contract():
    """Un mensaje corto que pide memoria no puede perder ese contexto."""
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("Claro")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    run(svc.run_turn(DAVID, [(DAVID, "¿te acuerdas de mi perro?")], TurnContext()))

    assert "FORMATO DE SALIDA OBLIGATORIO" in llm.last_system_prompt


def test_timeout_is_not_retried():
    """Reintentar tras un timeout solo duplicaría la espera."""
    state, _ = make_state()
    llm = FakeLLM(strict_error=asyncio.TimeoutError())
    svc = make_service(llm, state, notifier=FakeNotifier())

    with pytest.raises(asyncio.TimeoutError):
        run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert len(llm.calls) == 1


def test_turn_falls_back_when_strict_schema_unsupported():
    """Si el servidor rechaza la salida estricta, se reintenta en modo clásico."""
    state, _ = make_state()
    llm = FakeLLM(
        replies=[llm_json("hola tras el fallback")],
        strict_error=RuntimeError("400 Bad Request: json_schema"),
    )
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.reply == "hola tras el fallback"
    assert len(llm.calls) == 2
    assert llm.calls[0]["strict_schema"] is True
    assert llm.calls[1]["strict_schema"] is False


# ---------------------------------------------------------------------------
# Historial de asistente en JSON (refuerzo del formato de salida)
# ---------------------------------------------------------------------------


def test_history_stores_parse_repair_as_json():
    """Una salida sin JSON se repara y se guarda como JSON normalizado."""
    state, _ = make_state()
    llm = FakeLLM(replies=["hola sin json por parte del modelo", llm_json("hola reparado")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    entry = state.histories[0][-1]
    payload = json.loads(entry["content"])
    assert payload["reply"] == result.reply
    # El GIF es obligatorio: nunca se guarda "none" en el historial.
    assert payload["gif"] != "none"
    assert payload["gif"] == result.gif


def test_repeated_answer_with_json_history_is_published():
    """Una respuesta idéntica al historial JSON también se publica."""
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "David: hola"},
        {"role": "assistant", "content": llm_json("Ya te dije hola antes")},
    ]
    llm = FakeLLM(replies=[llm_json("Ya te dije hola antes")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.skipped is False
    assert result.reply == "Ya te dije hola antes"


def test_repeated_answer_with_plain_history_is_published():
    """Las entradas antiguas en texto plano tampoco bloquean la respuesta."""
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "David: hola"},
        {"role": "assistant", "content": "Ya te dije hola antes"},
    ]
    llm = FakeLLM(replies=[llm_json("Ya te dije hola antes")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.skipped is False
    assert result.reply == "Ya te dije hola antes"


# ---------------------------------------------------------------------------
# Afinidad, nivel y memoria
# ---------------------------------------------------------------------------


def test_turn_level_up_logs_diary_and_reflection():
    state, counters = make_state(affinity={"42": {"points": 24, "last_interaction": NOW,
                                                  "last_gain": 0.0, "milestones": []}})
    llm = FakeLLM(replies=[llm_json(
        "Eres mi amiga favorita",
        affinity_delta=2,
        affinity_event="me ha conquistado",
        diary="Hoy David me ha conquistado de verdad.",
    )])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "¿quién soy para ti?")], TurnContext()))

    assert result.leveled_up is True
    assert result.level_before == "Conocida"
    assert result.level_after == "Amiga"
    assert any(
        getattr(notice, "kind", None) == "level_up"
        and "Amiga" in getattr(notice, "text", "")
        for notice in result.notices
    )
    kinds = [k for k, _uid, _t in counters["diary_logs"]]
    assert "level" in kinds
    assert result.diary_saved is True
    assert any(e.get("kind") == "reflection" for e in state.diary)


def test_emotional_diary_reflection_is_saved_without_affinity_level_up():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json(
        "Gracias por confiarme esto.",
        diary="Hoy me conmovió que David confiara en mí con algo tan personal.",
    )])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(
        DAVID, [(DAVID, "quería contarte algo personal")], TurnContext()
    ))

    assert result.leveled_up is False
    assert result.diary_saved is True
    assert state.diary[-1]["kind"] == "reflection"
    assert "me conmovió" in state.diary[-1]["text"]


def test_turn_memory_saved_sends_notice():
    state, counters = make_state()
    notifier = FakeNotifier()
    llm = FakeLLM(replies=[llm_json("Lo apunto", memory="A David le encanta el ramen")])
    svc = make_service(llm, state, notifier=notifier)

    result = run(svc.run_turn(DAVID, [(DAVID, "me encanta el ramen")], TurnContext()))

    assert result.memory_saved is True
    assert counters["memories"] == 1
    assert any(
        getattr(notice, "kind", None) == "memory_saved"
        and "Airi recordará este evento" in getattr(notice, "text", "")
        for notice in notifier.sent
    )
    entries = state.user_memories(42)
    assert any("ramen" in e["text"] for e in entries)


def test_turn_memory_none_does_not_notify():
    state, _ = make_state()
    notifier = FakeNotifier()
    llm = FakeLLM(replies=[llm_json("nada que recordar")])
    svc = make_service(llm, state, notifier=notifier)

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.memory_saved is False
    assert all(
        getattr(notice, "kind", None) != "memory_saved"
        for notice in notifier.sent
    )


def test_turn_first_meeting_emits_notice_only_once():
    state, _ = make_state()
    notifier = FakeNotifier()
    llm = FakeLLM(replies=[llm_json("Hola~"), llm_json("Otra vez~")])
    svc = make_service(llm, state, notifier=notifier)

    first = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))
    second = run(svc.run_turn(DAVID, [(DAVID, "hola otra vez")], TurnContext()))

    assert any(
        getattr(notice, "kind", None) == "meet"
        and "David" in getattr(notice, "text", "")
        for notice in first.notices
    )
    assert all(
        getattr(notice, "kind", None) != "meet"
        for notice in second.notices
    )


def test_turn_negative_reaction_blocks_positive_affinity_and_memory():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json(
        "Ay, lo siento...",
        affinity_delta=1,
        affinity_event="KOKODA me ayudó a corregir detalles",
        memory="KOKODA ayuda a corregir detalles",
    )])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "noooooooo")], TurnContext()))

    assert result.affinity_delta == 1
    assert result.affinity_applied == 0
    assert state.entry_points(DAVID.id) == 0
    assert result.memory_saved is False
    assert state.user_memories(DAVID.id) == []


# ---------------------------------------------------------------------------
# Búsqueda web y grounding
# ---------------------------------------------------------------------------


def _search_tool_call(query="precio bitcoin hoy", motivo="me dio curiosidad"):
    return [{
        "id": "call-1",
        "name": "buscar_web",
        "arguments": {"query": query, "motivo": motivo},
    }]


def test_active_task_context_guides_search_and_is_returned_by_model():
    state, _ = make_state()
    state.histories[0] = [{
        "role": "assistant",
        "content": json.dumps({"reply": "Acabo de pensar en juegos de rol online."}),
        "system_generated": True,
    }]
    task_context = {
        "goal": "Identificar el anime de cada frase",
        "constraints": ["cinco frases", "dos vidas"],
        "progress": "Primera frase: Evangelion",
        "next_step": "Identificar la segunda frase",
    }
    output = json.loads(llm_json("Creo que es Digimon."))
    output["task_context_update"] = {
        "action": "set",
        **task_context,
        "progress": "Segunda frase: Digimon",
        "next_step": "Esperar la tercera frase",
    }
    llm = FakeLLM(
        replies=[json.dumps(output, ensure_ascii=False)],
        tool_calls=[_search_tool_call(
            "Moantai anime frase Digimon", "quiero identificar el anime del juego"
        )],
    )
    search = FakeSearch(result="La expresión aparece en Digimon Tamers.")
    svc = make_service(llm, state, search=search, notifier=FakeNotifier())
    svc.conversation_review_enabled = True

    result = run(svc.run_turn(
        DAVID,
        [(DAVID, "La siguiente frase es Moantai")],
        TurnContext(task_context=task_context),
    ))

    decision_context = llm.decision_calls[0]["messages"][-1]["content"]
    assert "Identificar el anime de cada frase" in decision_context
    assert "Identificar el anime de cada frase" in llm.calls[0]["messages"][0]["content"]
    assert "Identificar el anime de cada frase" in llm.calls[-1]["messages"][-1]["content"]
    assert search.queries == ["Moantai anime frase Digimon"]
    assert result.task_context_update["progress"] == "Segunda frase: Digimon"
    trace_json = json.dumps(result.trace.to_dict(), ensure_ascii=False)
    assert "Identificar el anime de cada frase" not in trace_json
    assert "Adivinar la segunda frase" not in trace_json
    assert "marco efímero omitido de la traza" in result.trace.prompt_system


def test_turn_web_search_is_decided_by_native_tool_call():
    state, _ = make_state()
    notifier = FakeNotifier()
    search = FakeSearch(result="Bitcoin ronda los 30 mil euros.")
    llm = FakeLLM(
        replies=[llm_json("Madre mía, ronda los 30 mil euros~")],
        tool_calls=[_search_tool_call()],
    )
    svc = make_service(llm, state, search=search, notifier=notifier)

    result = run(svc.run_turn(
        DAVID, [(DAVID, "¿A cuánto está Bitcoin?")], TurnContext()
    ))

    assert search.queries == ["precio bitcoin hoy"]
    assert result.reply == "Madre mía, ronda los 30 mil euros~"
    assert result.grounded is True
    assert result.trace.web_requested is True
    assert result.trace.web_motivo == "me dio curiosidad"
    assert result.trace.web_query == "precio bitcoin hoy"
    assert "Has buscado porque me dio curiosidad" in llm.last_system_prompt
    assert "30 mil euros" in llm.last_system_prompt
    assert "Fuente 1" not in llm.last_system_prompt
    assert any(getattr(n, "kind", None) == "web_search" for n in notifier.sent)


def test_turn_no_search_when_model_declines_even_for_explicit_words():
    state, _ = make_state()
    search = FakeSearch(result="no debe usarse")
    llm = FakeLLM(replies=[llm_json("Te entiendo~")])
    svc = make_service(llm, state, search=search, notifier=FakeNotifier())

    result = run(svc.run_turn(
        DAVID, [(DAVID, "búscalo en internet, era una broma")], TurnContext()
    ))

    assert search.queries == []
    assert result.trace.web_requested is False
    assert result.web_context is None
    assert len(llm.calls) == 1
    assert len(llm.decision_calls) == 1
    assert llm.decision_calls[0]["tools"]


def test_turn_no_search_when_web_disabled():
    state, _ = make_state()
    search = FakeSearch(result="nunca debería usarse")
    llm = FakeLLM(replies=[llm_json("hola")])
    svc = make_service(llm, state, search=search, notifier=FakeNotifier())

    result = run(svc.run_turn(
        DAVID, [(DAVID, "¿A cuánto está BTC?")], TurnContext(allow_web=False)
    ))

    assert search.queries == []
    assert len(llm.calls) == 1
    assert result.web_context is None


@pytest.mark.parametrize("mode", ["active", "spectator"])
def test_conversational_modes_offer_web_but_model_decides(mode):
    state, _ = make_state()
    llm = FakeLLM(
        replies=[llm_json("Lo comprobé: aquí están los datos.", stay_active=True)],
        tool_calls=[_search_tool_call("dato actual", "quería verificarlo")],
    )
    search = FakeSearch(result="dato verificado")
    svc = make_service(llm, state, search=search, notifier=FakeNotifier())

    result = run(svc.run_turn(
        DAVID,
        [(DAVID, "¿Cuál es el dato actual?")],
        TurnContext(kind=mode, conversation_mode=mode),
    ))

    assert result.trace.allow_web is True
    assert len(llm.decision_calls) == 1
    assert search.queries == ["dato actual"]
    assert result.trace.web_requested is True


def test_active_turn_respects_global_web_search_toggle():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("Respondo sin búsqueda.", stay_active=True)])
    search = FakeSearch(result="no debe buscarse")
    svc = make_service(llm, state, search=search, notifier=FakeNotifier())
    svc.web_search_enabled = False

    result = run(svc.run_turn(
        DAVID,
        [(DAVID, "¿Cuál es el dato actual?")],
        TurnContext(kind="active", conversation_mode="active"),
    ))

    assert result.trace.allow_web is True
    assert not llm.decision_calls
    assert not search.queries


def test_proactive_turn_does_not_offer_web():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("Te cuento algo sin buscar.", stay_active=False)])
    search = FakeSearch(result="no debe buscarse")
    svc = make_service(llm, state, search=search, notifier=FakeNotifier())

    result = run(svc.run_turn(
        DAVID,
        [(DAVID, "¿Cuál es el dato actual?")],
        TurnContext(kind="proactive", conversation_mode="proactive"),
    ))

    assert not llm.decision_calls
    assert not search.queries
    assert result.trace.allow_web is False


def test_ungrounded_web_reply_is_preserved_and_only_recorded():
    state, _ = make_state()
    search = FakeSearch(result="Las noticias hablan de una nueva temporada.")
    answer = (
        "Estrenan el 4 de enero, luego el 5 de febrero y el 6 de marzo "
        "la tercera parte"
    )
    llm = FakeLLM(
        replies=[llm_json(answer, affinity_delta=5,
                          affinity_event="noticia increíble", gif="happy")],
        tool_calls=[_search_tool_call("noticias anime", "quería comprobarlo")],
    )
    svc = make_service(llm, state, search=search, gifs=FakeGif(),
                       notifier=FakeNotifier())

    result = run(svc.run_turn(
        DAVID, [(DAVID, "¿Qué noticias hay del anime?")], TurnContext()
    ))

    assert result.grounded is False
    assert result.reply == answer
    assert result.trace.web_grounded is False
    assert result.affinity_applied == 5  # grounding no modifica el resultado
    assert result.gif == "happy"


def test_search_failure_does_not_replace_model_reply():
    state, _ = make_state()
    llm = FakeLLM(
        replies=[llm_json("Uf, no encontré nada claro; qué raro~")],
        tool_calls=[_search_tool_call()],
    )
    svc = make_service(llm, state, search=FakeSearch(result=None),
                       notifier=FakeNotifier())

    result = run(svc.run_turn(
        DAVID, [(DAVID, "¿Cuál es el precio actual de BTC?")], TurnContext()
    ))

    assert result.reply == "Uf, no encontré nada claro; qué raro~"
    assert result.trace.web_requested is True
    assert result.trace.web_grounded is False


# ---------------------------------------------------------------------------
# GIFs, citas y prompt
# ---------------------------------------------------------------------------


def test_turn_fetches_gif_when_model_selects_one():
    state, _ = make_state()
    gifs = FakeGif(data=b"GIF89a-happy")
    llm = FakeLLM(replies=[llm_json("¡Siii~!", gif="happy")])
    svc = make_service(llm, state, gifs=gifs, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hoy es un gran día")], TurnContext()))

    assert result.gif == "happy"
    assert result.gif_bytes == b"GIF89a-happy"
    assert gifs.requested == ["happy"]


def test_turn_forces_gif_when_model_returns_none():
    """Aunque el modelo devuelva none, el turno siempre pide un GIF."""
    state, _ = make_state()
    gifs = FakeGif(data=b"GIF89a-happy")
    llm = FakeLLM(replies=[llm_json("hola", gif="none")])
    svc = make_service(llm, state, gifs=gifs, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.gif == "happy"
    assert result.gif_bytes == b"GIF89a-happy"
    assert gifs.requested == ["happy"]


def test_turn_in_date_keeps_the_question_and_uses_date_delta_max():
    state, counters = make_state()
    session = new_date_session("cena romántica", 10, now=NOW)
    state.dates["42"] = session
    llm = FakeLLM(replies=[llm_json(
        "Airi se sonroja",
        affinity_delta=99,
        affinity_event="cena increíble",
        date_question={
            "text": "¿Qué es lo que más te gusta de mí?",
            "options": [
                {
                    "label": "Tu risa",
                    "action": "le digo que su risa",
                    "up_chance": 0.8,
                    "delta_up": 20,
                    "delta_down": -8,
                },
                {
                    "label": "Tu compañía",
                    "action": "le digo que su compañía",
                    "up_chance": 0.6,
                    "delta_up": 12,
                    "delta_down": -6,
                },
            ],
        },
    )])
    svc = make_service(llm, state, notifier=FakeNotifier(), date_delta_max=8)

    result = run(svc.run_turn(DAVID, [(DAVID, "la cena está genial")], TurnContext()))

    assert result.in_date is True
    assert result.trace.allow_web is False
    assert not llm.decision_calls
    assert result.affinity_applied == 8  # tope ampliado durante la cita
    assert result.date_question["text"] == "¿Qué es lo que más te gusta de mí?"
    assert len(result.date_question["options"]) == 2
    # El historial de la cita queda aislado en la sesión.
    assert session["history"][-1]["role"] == "assistant"
    assert counters["dates"] == 1
    assert 0 not in state.histories


def test_turn_outside_date_drops_the_question():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json(
        "hola",
        date_question={
            "text": "¿Qué es lo que más te gusta de mí?",
            "options": [
                {
                    "label": "x",
                    "action": "y",
                    "up_chance": 0.5,
                    "delta_up": 5,
                    "delta_down": -5,
                },
            ],
        },
    )])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.in_date is False
    assert result.date_question is None


def test_system_prompt_includes_affinity_and_user():
    state, _ = make_state(affinity={"42": {"points": 30, "last_interaction": NOW,
                                           "last_gain": 0.0, "milestones": []}})
    llm = FakeLLM(replies=[llm_json("hola")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    prompt = llm.last_system_prompt
    assert "=== AFINIDAD CON ESTE USUARIO ===" in prompt
    assert "David" in prompt
    assert "30 puntos" in prompt
    assert "=== RELACIÓN ===" in prompt
    assert "=== TUS PREFERENCIAS CANÓNICAS ===" in prompt
    # La llamada va con el esquema JSON de respuesta.
    assert llm.calls[-1]["schema"] is not None




# ---------------------------------------------------------------------------
# Corte por techo de tokens: reintento único sin razonamiento
# ---------------------------------------------------------------------------


def test_truncated_generation_retries_with_low_effort():
    state, _ = make_state()
    llm = FakeLLM(
        replies=["", llm_json("Me quedé pensando, pero aquí estoy.")],
        metas=[
            LLMMeta(finish_reason="length"),
            LLMMeta(finish_reason="stop"),
        ],
    )
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.skipped is False
    assert result.reply == "Me quedé pensando, pero aquí estoy."
    assert len(llm.calls) == 2
    assert llm.calls[1]["reasoning_budget_tokens"] == 256
    assert "sin razonar" not in llm.calls[1]["messages"][-1]["content"]


def test_normal_turn_ignores_stay_active_false():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("Hola.", stay_active=False)])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.stay_active is True
    assert result.trace.stay_active is True
    assert result.trace.disconnect is None


def test_truncated_session_turn_retries_and_keeps_stay_active():
    state, _ = make_state()
    llm = FakeLLM(
        replies=["", llm_json("Sigo aquí.", stay_active=False)],
        metas=[
            LLMMeta(finish_reason="length"),
            LLMMeta(finish_reason="stop"),
        ],
    )
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(
        svc.run_turn(
            DAVID,
            [(DAVID, "hola")],
            TurnContext(kind="proactive", conversation_mode="proactive"),
        )
    )

    assert result.skipped is False
    assert result.reply == "Sigo aquí."
    assert result.stay_active is False
    assert len(llm.calls) == 2
    assert llm.calls[1]["reasoning_budget_tokens"] == 256
    assert "stay_active" in llm.calls[1]["messages"][-1]["content"]


def test_valid_reply_is_not_retried_even_if_finish_reason_is_length():
    state, _ = make_state()
    llm = FakeLLM(
        replies=[llm_json("Respuesta completa.")],
        metas=[LLMMeta(finish_reason="length")],
    )
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.reply == "Respuesta completa."
    assert len(llm.calls) == 1


def test_truncated_generation_without_recovery_skips_without_raw_json():
    state, _ = make_state()
    raw_truncado = '{"reply": "me quedé pensando y el JSON se co'
    llm = FakeLLM(
        replies=[raw_truncado, raw_truncado],
        metas=[
            LLMMeta(finish_reason="length"),
            LLMMeta(finish_reason="length"),
        ],
    )
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.skipped is True
    assert not result.reply
    assert len(llm.calls) == 2
