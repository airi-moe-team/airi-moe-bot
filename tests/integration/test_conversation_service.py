"""Tests de integración de ConversationService con fakes (sin red ni Discord)."""

import asyncio
import json

from airi.domain.constants import DATE_QUESTION_MIN_TURNS, SEARCH_QUERY_MAX_TOKENS
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


def test_turn_duplicate_answer_is_skipped():
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "David: hola"},
        {"role": "assistant", "content": "Ya te dije hola antes"},
    ]
    llm = FakeLLM(replies=[llm_json("Ya te dije hola antes")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.skipped is True
    assert result.reply is None
    # En skip no se persiste nada: el historial sigue igual que antes.
    assert len(state.histories[0]) == 2
    assert state.histories[0][-1] == {
        "role": "assistant", "content": "Ya te dije hola antes"}


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
    assert payload["gif"] == "none"


def test_duplicate_detection_works_with_json_history():
    """El filtro de duplicados extrae el reply del historial JSON."""
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "David: hola"},
        {"role": "assistant", "content": llm_json("Ya te dije hola antes")},
    ]
    llm = FakeLLM(replies=[llm_json("Ya te dije hola antes")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.skipped is True
    assert result.reply is None


def test_history_keeps_plain_legacy_entries_working():
    """Las entradas antiguas en texto plano siguen comparándose correctamente."""
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "David: hola"},
        {"role": "assistant", "content": "Ya te dije hola antes"},
    ]
    llm = FakeLLM(replies=[llm_json("Ya te dije hola antes")])
    svc = make_service(llm, state, notifier=FakeNotifier())

    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))

    assert result.skipped is True


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
    # Todo se pone a cero: ni afinidad ni GIF.
    assert result.affinity_delta == 0
    assert result.gif == "none"
    assert result.gif_bytes is None
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


def test_turn_in_date_keeps_question_and_uses_date_delta_max():
    state, counters = make_state()
    session = new_date_session("cena romántica", 10, now=NOW)
    session["turns"] = DATE_QUESTION_MIN_TURNS  # turno mínimo para preguntar
    state.dates["42"] = session
    llm = FakeLLM(replies=[llm_json(
        "Airi se sonroja",
        affinity_delta=99,
        affinity_event="cena increíble",
        date_decision="question",
        date_question={
            "text": "¿Qué es lo que más te gusta de mí?",
            "options": [
                {"label": "Cómo me escuchas", "action": "la escuchas",
                 "up_chance": 0.85, "delta_up": 22, "delta_down": -6},
            ],
        },
    )])
    svc = make_service(llm, state, notifier=FakeNotifier(), date_delta_max=8)

    result = run(svc.run_turn(DAVID, [(DAVID, "la cena está genial")], TurnContext()))

    assert result.in_date is True
    assert result.affinity_applied == 8  # tope ampliado durante la cita
    assert result.date_decision == "question"
    assert result.date_question["text"] == "¿Qué es lo que más te gusta de mí?"
    # El historial de la cita queda aislado en la sesión.
    assert session["history"][-1]["role"] == "assistant"
    assert counters["dates"] == 1
    assert 0 not in state.histories


def test_turn_outside_date_drops_question():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json(
        "hola",
        date_question={
            "text": "¿pregunta fuera de cita?",
            "options": [{"label": "x", "action": "y", "up_chance": 0.5,
                         "delta_up": 1, "delta_down": -1}],
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


