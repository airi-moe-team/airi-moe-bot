"""Tests de integración de ConversationService con fakes (sin red ni Discord)."""

import asyncio
import json

import pytest

from airi.domain.constants import LLM_SHORT_MAX_TOKENS, SEARCH_QUERY_MAX_TOKENS
from airi.domain.dates import new_date_session
from airi.services.conversation import (
    GROUNDED_FALLBACK_TEXT,
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


def test_turn_invalid_json_recovers_raw_reply():
    state, _ = make_state()
    llm = FakeLLM(replies=["esto no es json pero tiene reply: hola"])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.reply == "esto no es json pero tiene reply: hola"
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
    # El límite breve no deja sitio al razonamiento: debe desactivarse.
    assert llm.calls[-1]["disable_thinking"] is True


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
    assert llm.calls[-1]["disable_thinking"] is False


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


def test_history_stores_plain_fallback_as_json():
    """Aunque el modelo se salga del JSON, el historial se guarda como JSON."""
    state, _ = make_state()
    llm = FakeLLM(replies=["hola sin json por parte del modelo"])
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
    kinds = [k for k, _uid, _t in counters["diary_logs"]]
    assert "level" in kinds
    assert result.diary_saved is True
    assert any(e.get("kind") == "reflection" for e in state.diary)


def test_turn_memory_saved_sends_notice():
    state, counters = make_state()
    notifier = FakeNotifier()
    llm = FakeLLM(replies=[llm_json("Lo apunto", memory="A David le encanta el ramen")])
    svc = make_service(llm, state, notifier=notifier)

    result = run(svc.run_turn(DAVID, [(DAVID, "me encanta el ramen")], TurnContext()))

    assert result.memory_saved is True
    assert counters["memories"] == 1
    assert "Airi recordará este evento" in notifier.sent
    entries = state.user_memories(42)
    assert any("ramen" in e["text"] for e in entries)


def test_turn_memory_none_does_not_notify():
    state, _ = make_state()
    notifier = FakeNotifier()
    llm = FakeLLM(replies=[llm_json("nada que recordar")])
    svc = make_service(llm, state, notifier=notifier)

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.memory_saved is False
    assert notifier.sent == []


# ---------------------------------------------------------------------------
# Búsqueda web y grounding
# ---------------------------------------------------------------------------


def test_turn_web_search_reformulates_and_uses_context():
    state, _ = make_state()
    notifier = FakeNotifier()
    search = FakeSearch(result="Fuente 1: BTC\nURL: https://x.test\nResumen: 30k")
    # Primera respuesta: la consulta reformulada; segunda: el JSON final.
    llm = FakeLLM(replies=[
        "precio bitcoin hoy",
        llm_json("El precio ronda los 30k según he buscado~"),
    ])
    svc = make_service(llm, state, search=search, notifier=notifier)

    result = run(svc.run_turn(
        DAVID, [(DAVID, "búscame en internet el precio de bitcoin")], TurnContext()
    ))

    assert "Un momentito, estoy buscando información en la web..." in notifier.sent
    assert search.queries == ["precio bitcoin hoy"]
    assert "30k" in result.reply
    assert result.grounded is True
    assert result.web_context is not None
    # El prompt de la llamada principal incluye el contexto web.
    assert "=== RESULTADOS DE BÚSQUEDA ===" in llm.last_system_prompt
    # La primera llamada (reformulación de búsqueda) respeta SEARCH_QUERY_MAX_TOKENS.
    assert llm.calls[0]["max_tokens"] == SEARCH_QUERY_MAX_TOKENS


def test_turn_web_search_failure_sets_honest_context():
    state, _ = make_state()
    search = FakeSearch(result=None)
    llm = FakeLLM(replies=[
        "precio bitcoin hoy",
        llm_json("No he encontrado información fiable sobre eso en la web"),
    ])
    svc = make_service(llm, state, search=search, notifier=FakeNotifier())

    result = run(svc.run_turn(
        DAVID, [(DAVID, "búscame en internet el precio de bitcoin")], TurnContext()
    ))

    assert "falló o no devolvió resultados" in result.web_context


def test_turn_ungrounded_reply_is_replaced():
    state, _ = make_state()
    search = FakeSearch(result="Fuente 1: Anime\nURL: https://x.test\nResumen: noticias")
    llm = FakeLLM(replies=[
        "busqueda anime",
        llm_json(
            "Estrenan el 4 de enero, luego el 5 de febrero y el 6 de marzo "
            "la tercera parte",
            affinity_delta=5,
            affinity_event="noticia increíble",
            gif="happy",
        ),
    ])
    svc = make_service(llm, state, search=search, gifs=FakeGif(),
                       notifier=FakeNotifier())

    result = run(svc.run_turn(
        DAVID, [(DAVID, "búscame en internet noticias del anime")], TurnContext()
    ))

    assert result.grounded is False
    assert result.reply == GROUNDED_FALLBACK_TEXT
    # La afinidad se anula, pero el turno conserva su GIF obligatorio.
    assert result.affinity_delta == 0
    assert result.gif == "happy"
    assert result.gif_bytes == b"GIF89a-fake"
    assert state.entry_points(42) == 0


def test_turn_no_web_when_disabled():
    state, _ = make_state()
    search = FakeSearch(result="nunca debería usarse")
    llm = FakeLLM(replies=[llm_json("hola")])
    svc = make_service(llm, state, search=search, notifier=FakeNotifier())

    result = run(svc.run_turn(
        DAVID, [(DAVID, "búscame en internet algo")], TurnContext(allow_web=False)
    ))

    assert search.queries == []
    assert result.web_context is None
    assert "=== RESULTADOS DE BÚSQUEDA ===" not in llm.last_system_prompt


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
    assert "=== NIVEL DE AFINIDAD CON EL USUARIO ===" in prompt
    assert "David" in prompt
    assert "30 puntos" in prompt
    assert "=== ESTADO DE VUESTRA RELACIÓN ===" in prompt
    assert "=== TUS GUSTOS (SECRETOS) ===" in prompt
    # La llamada va con el esquema JSON de respuesta.
    assert llm.calls[-1]["schema"] is not None


