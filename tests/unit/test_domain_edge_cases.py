"""Casos límite del dominio y servicios (endurecimiento de la Fase 6).

Cubre las ramas defensivas que la suite funcional no toca: entradas
corruptas, argumentos no dict, techos de recuperación, monogamia en los
prompts, cooldowns del diario y fallos de los callbacks de persistencia.
"""

import asyncio

from airi.domain import affinity as A
from airi.domain import dates as D
from airi.domain import diary as DI
from airi.domain import prompts as P
from airi.services.conversation import ConversationService, TurnContext
from airi.services.date_service import DateService
from airi.services.state import AppState
from airi.testing import FakeLLM, FakeNotifier, FakeSearch, FakeUser, llm_json, make_state

NOW = 1_000_000.0
DAVID = FakeUser(42, "David")


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# domain.affinity
# ---------------------------------------------------------------------------


def test_entry_points_tolerates_garbage():
    assert A.entry_points(None) == 0
    assert A.entry_points("nope") == 0
    assert A.entry_points({"points": "abc"}) == 0
    assert A.entry_points({"points": 7}) == 7


def test_maybe_crown_winner_edge_cases():
    assert A.maybe_crown_winner(None, {}, NOW) is None
    world = {"winner_id": "9"}
    assert A.maybe_crown_winner(world, {"1": {"points": 100}}, NOW) is None
    # Entradas internas "_" se ignoran.
    data = {"_meta": {"points": 100}, "1": {"points": 100}}
    assert A.maybe_crown_winner({"winner_id": None}, data, NOW) == "1"


def test_maybe_crown_winner_tie_breaks_by_smaller_id():
    data = {"20": {"points": 100}, "10": {"points": 100}}
    world = {}
    assert A.maybe_crown_winner(world, data, NOW) == "10"
    assert world["relationship_started_at"] == float(NOW)


def test_is_winner_non_dict_world():
    assert A.is_winner(None, "1") is False
    assert A.is_winner({"winner_id": "1"}, 1) is True


def test_apply_winner_lock_caps_losers_only():
    world = {"winner_id": "1"}
    data = {
        "1": {"points": 90},
        "2": {"points": 80},
        "_meta": {"points": 80},
        "3": "no soy dict",
    }
    A.apply_winner_lock(world, data)
    assert data["1"]["points"] == 90  # el ganador no se toca
    assert data["2"]["points"] == A.FRIENDZONE_CAP
    assert data["_meta"]["points"] == 80  # las entradas "_" se saltan
    assert data["3"] == "no soy dict"


def test_apply_winner_lock_noop_without_winner():
    data = {"1": {"points": 80}}
    A.apply_winner_lock({}, data)
    assert data["1"]["points"] == 80


def test_ranking_skips_internal_and_non_dict():
    rows = A.ranking(
        {"_meta": {"points": 99}, "1": {"points": 10}, "2": "basura"},
        {"1": {"name": "Ana"}},
    )
    assert [r["user_id"] for r in rows] == ["1"]


def test_decay_hits_floor_never_below():
    entry = {"points": -98, "last_interaction": NOW - 10 * 86400}
    applied = A.apply_affinity_delta(entry, 0, NOW)
    assert entry["points"] == A.AFFINITY_FLOOR
    assert applied == 0


# ---------------------------------------------------------------------------
# domain.dates
# ---------------------------------------------------------------------------


def test_normalize_date_session_repairs_bad_values():
    session = D.normalize_date_session({
        "state": "inventado", "turns": "x", "affinity_start": "y",
        "history": "no lista",
    })
    assert session["state"] == "active"
    assert session["turns"] == 0
    assert session["affinity_start"] == 0
    assert session["history"] == []
    assert D.normalize_date_session("no dict") is None


def test_date_helpers_tolerate_garbage():
    assert D.date_turns_left(None) == 0
    assert D.date_turns_left({"turns": "x"}) == D.DATE_MAX_TURNS
    assert D.date_seconds_left(None, NOW) == 0
    assert D.date_seconds_left({"started_at": "x"}, NOW) == 0
    assert D.date_seconds_left({"state": "closed", "started_at": NOW}, NOW) == 0
    assert D.date_expired(None, NOW) is False
    assert D.date_expired({"started_at": "x"}, NOW) is False
    assert D.date_expired({"state": "closed", "started_at": 0}, NOW) is False


def test_crisis_allowed_guards():
    assert D.crisis_allowed(None) is False
    assert D.crisis_allowed({"state": "last_chance", "turns": 9}) is False
    assert D.crisis_allowed({"state": "active", "turns": 9, "last_chance_used": True}) is False
    assert D.crisis_allowed({"state": "active", "turns": "x"}) is False


def test_end_allowed_guards():
    assert D.end_allowed(None) is False
    assert D.end_allowed({"state": "final_scene", "turns": 9}) is False


def test_resolve_date_at_limit_partial_recovery():
    session = {"state": "last_chance", "last_chance_result": "partial"}
    assert D.resolve_date_at_limit(session, 5) == "partial_recovery"
    assert session["state"] == "final_scene"
    session2 = {"state": "last_chance", "last_chance_result": "none"}
    assert D.resolve_date_at_limit(session2, 5) == "failed_last_chance"
    assert D.resolve_date_at_limit("no dict") == "closed"


def test_last_chance_recovery_guards():
    assert D.last_chance_recovery({"affinity_start": 40}, "partial", 30) == 6
    assert D.last_chance_recovery({"affinity_start": "x"}, "success", "y") == 0
    assert D.last_chance_recovery({"affinity_start": 10}, "desconocido", 30) == 0
    # Nunca por encima del inicio de la cita.
    assert D.last_chance_recovery({"affinity_start": 10}, "success", 40) == 0


# ---------------------------------------------------------------------------
# domain.diary
# ---------------------------------------------------------------------------


def test_diary_guards():
    assert DI.default_diary() == []
    assert DI.add_diary_entry("no lista", {"text": "x"}) is False
    assert DI.add_diary_entry([], {"kind": "gift"}) is False  # sin texto
    assert DI.diary_for_user("no lista", 1) == []
    assert DI.recent_diary(None) == []
    assert DI.purge_user_diary(None, 1) == 0
    diary = [
        DI.new_diary_entry("gift", 1, "Ana", "uno", NOW),
        DI.new_diary_entry("gift", 2, "Beto", "dos", NOW),
    ]
    assert len(DI.diary_for_user(diary, 1)) == 1
    assert DI.diary_for_user(diary, 1, limit=-1) == DI.diary_for_user(diary, 1)
    assert DI.recent_diary(diary, limit=1) == [diary[1]]
    assert DI.purge_user_diary(diary, 1) == 1


def test_format_relative_time_branches_and_guard():
    assert DI.format_relative_time("x", NOW) == ""
    assert DI.format_relative_time(NOW - 30, NOW) == "ahora mismo"
    assert DI.format_relative_time(NOW - 120, NOW) == "hace 2 min"
    assert DI.format_relative_time(NOW - 7200, NOW) == "hace 2 h"
    assert DI.format_relative_time(NOW - 86400, NOW) == "ayer"
    assert DI.format_relative_time(NOW - 3 * 86400, NOW) == "hace 3 días"


# ---------------------------------------------------------------------------
# domain.prompts
# ---------------------------------------------------------------------------


def test_relationship_section_novio_counts_days():
    world = {"winner_id": "42", "relationship_started_at": NOW - 2 * 86400}
    text = P.relationship_status_section(
        world, {}, user_id=42, display_name="David", now=NOW
    )
    assert "es TU NOVIO" in text
    assert "3 día(s)" in text


def test_relationship_section_winner_known_and_unknown():
    world = {"winner_id": "9"}
    with_name = P.relationship_status_section(
        world, {"9": {"name": "Ana"}}, user_id=42, display_name="David", now=NOW
    )
    assert "Ya tienes novio: Ana" in with_name
    unknown = P.relationship_status_section(
        world, {}, user_id=42, display_name="David", now=NOW
    )
    assert "Ya tienes novio: otra persona" in unknown


def test_prompt_sections_user_none_are_empty():
    assert P.diary_prompt_section([], None, NOW) == ""
    assert P.known_users_prompt_section({}, [], {}, user_id=None,
                                        display_name="David") == ""
    assert P.date_context_section(None) == ""
    assert P.date_context_section("no dict") == ""


def test_memories_prompt_section_with_entries():
    text = P.memories_prompt_section([{"text": "Le gusta el ramen"}])
    assert "1. Le gusta el ramen" in text
    assert "olvidar: <número>" in text
    assert "Todavía no recuerdas" not in text
    empty = P.memories_prompt_section([])
    assert "Todavía no recuerdas" in empty


def test_known_users_monogamy_hides_others():
    users = {"42": {"name": "David", "last_seen": NOW, "interactions": 3},
             "9": {"name": "Ana", "last_seen": NOW, "interactions": 5}}
    diary = [DI.new_diary_entry("meet", 9, "Ana", "Ana mola", NOW)]
    world = {"winner_id": "42"}
    text = P.known_users_prompt_section(
        users, diary, world, user_id=42, display_name="David"
    )
    assert "Ana" not in text  # con pareja, Airi solo piensa en el ganador
    assert "David" in text


def test_date_context_section_last_chance_mentions_reason():
    session = D.new_date_session("cena", 10, NOW)
    session["state"] = "last_chance"
    session["crisis_reason"] = "se pasó de la raya"
    text = P.date_context_section(session)
    assert "ÚLTIMA OPORTUNIDAD" in text
    assert "se pasó de la raya" in text


# ---------------------------------------------------------------------------
# services: ramas defensivas
# ---------------------------------------------------------------------------


class BrokenNotifier(FakeNotifier):
    async def send(self, content):
        self.sent.append(content)
        raise RuntimeError("Discord caído")


def test_memory_notice_failure_does_not_break_turn():
    state, _ = make_state()
    llm = FakeLLM(replies=[llm_json("Lo apunto", memory="Le encanta el ramen")])
    svc = ConversationService(
        llm=llm, state=state, notifier=BrokenNotifier(), clock=lambda: NOW
    )
    result = run(svc.run_turn(DAVID, [(DAVID, "me encanta el ramen")],
                              TurnContext()))
    assert result.memory_saved is True  # la memoria se guardó igual


def test_model_without_reply_marks_skipped():
    state, _ = make_state()
    llm = FakeLLM(replies=["{}"])  # JSON válido sin reply
    svc = ConversationService(
        llm=llm, state=state, notifier=FakeNotifier(), clock=lambda: NOW
    )
    result = run(svc.run_turn(DAVID, [(DAVID, "hola")], TurnContext()))
    assert result.skipped is True
    assert result.reply is None
    assert result.trace.raw_llm == "{}"


class ExplodingLLM(FakeLLM):
    """Falla solo al reformular la búsqueda (llamada sin `json_schema`)."""

    async def chat(self, messages, **kwargs):
        if "schema" not in kwargs:
            import aiohttp

            raise aiohttp.ClientError("sin red")
        return await super().chat(messages, **kwargs)


def test_search_query_failure_falls_back_to_original():
    state, _ = make_state()
    search = FakeSearch(result=None)
    llm = ExplodingLLM(replies=[llm_json("no pude buscar bien")])
    svc = ConversationService(
        llm=llm, state=state, search=search, notifier=FakeNotifier(),
        clock=lambda: NOW,
    )
    result = run(svc.run_turn(
        DAVID, [(DAVID, "búscame en internet el precio del oro")], TurnContext(),
    ))
    # La consulta original se usa tal cual y el turno continúa.
    assert search.queries == ["búscame en internet el precio del oro"]
    assert result.reply == "no pude buscar bien"


def test_reflection_cooldown_blocks_second_one():
    from airi.domain.diary import new_diary_entry

    state, _ = make_state(
        affinity={"42": {"points": 24, "last_interaction": NOW,
                         "last_gain": 0.0, "milestones": []}},
    )
    state.diary.append(new_diary_entry(
        "reflection", 42, "David", "una reflexión reciente", NOW,
    ))
    llm = FakeLLM(replies=[llm_json(
        "hoy es el día", affinity_delta=2, affinity_event="me conquistó",
        diary="otra reflexión distinta",
    )])
    svc = ConversationService(
        llm=llm, state=state, notifier=FakeNotifier(), clock=lambda: NOW
    )
    result = run(svc.run_turn(DAVID, [(DAVID, "hoy es el día")], TurnContext()))
    assert result.leveled_up is True
    assert result.diary_saved is False  # dentro del cooldown de 600 s


def test_duplicate_reflection_is_blocked():
    from airi.domain.diary import new_diary_entry

    state, _ = make_state(
        affinity={"42": {"points": 24, "last_interaction": NOW,
                         "last_gain": 0.0, "milestones": []}},
    )
    state.diary.append(new_diary_entry(
        "reflection", 42, "David", "mismo texto exacto", NOW - 10 * 86400,
    ))
    llm = FakeLLM(replies=[llm_json(
        "hoy es el día", affinity_delta=2, affinity_event="me conquistó",
        diary="mismo texto exacto",
    )])
    svc = ConversationService(
        llm=llm, state=state, notifier=FakeNotifier(), clock=lambda: NOW
    )
    result = run(svc.run_turn(DAVID, [(DAVID, "hoy es el día")], TurnContext()))
    assert result.leveled_up is True
    assert result.diary_saved is False  # texto idéntico reciente


def test_empty_diary_action_is_not_saved():
    state, _ = make_state(
        affinity={"42": {"points": 24, "last_interaction": NOW,
                         "last_gain": 0.0, "milestones": []}},
    )
    llm = FakeLLM(replies=[llm_json(
        "hoy es el día", affinity_delta=2, affinity_event="me conquistó",
        diary="   ",
    )])
    svc = ConversationService(
        llm=llm, state=state, notifier=FakeNotifier(), clock=lambda: NOW
    )
    result = run(svc.run_turn(DAVID, [(DAVID, "hoy es el día")], TurnContext()))
    assert result.leveled_up is True
    assert result.diary_saved is False


def test_state_defaults_are_safe_noops():
    state = AppState()  # sin callbacks: los defaults no deben explotar
    entry = state.affinity_entry(7)
    entry["points"] = 5
    assert state.entry_points(7) == 5
    applied = state.apply_affinity(7, 2, now=NOW)
    assert applied == 2
    assert state.entry_points(7) == 7
    assert state.display_name(7) == "alguien"
    assert state.user_memories(7) == []
    state.save_affinity()
    state.log_diary_event("meet", 7, "hola")


def test_state_apply_affinity_hook_none_is_coerced():
    state, _ = make_state()
    state.apply_affinity_fn = lambda uid, delta, now=None, delta_max=None: None
    assert state.apply_affinity(1, 3, now=NOW) == 0


def test_date_service_uses_clock_when_now_missing():
    state, _ = make_state()
    session = D.new_date_session("paseo", 40, NOW)
    state.dates["1"] = session
    user = FakeUser(1, "Ana")
    service = DateService(state=state, notifier=None, clock=lambda: NOW + 60)
    event = run(service.process_turn(
        session, user=user, text="hola", delta=0, points=40,
        date_decision="continue", date_reason="none",
        last_chance_result="none", now=None,
    ))
    assert event == "continue"
    assert session["started_at"] == NOW


def test_date_service_time_fallback_without_clock():
    state, _ = make_state()
    session = D.new_date_session("paseo", 40, NOW)
    state.dates["1"] = session
    user = FakeUser(1, "Ana")
    service = DateService(state=state, notifier=None, clock=None)
    event = run(service.process_turn(
        session, user=user, text="hola", delta=0, points=40,
        date_decision="continue", date_reason="none",
        last_chance_result="none", now=None,
    ))
    assert event == "continue"
    assert session["started_at"] > 0






# --- regresión: clamp_delta tolera límites None (TypeError visto en run_bot) ---

def test_clamp_delta_tolerates_none_bounds():
    # El wiring de run_bot puede reenviar delta_min=None: debe caer al
    # mínimo del dominio en vez de reventar con TypeError.
    assert A.clamp_delta(3, 5, None) == 3
    assert A.clamp_delta(-99, 5, None) == A.AFFINITY_DELTA_MIN
    assert A.clamp_delta(99, None, None) == A.AFFINITY_DELTA_MAX
    assert A.clamp_delta(2, None, 0) == 2


def test_apply_affinity_with_run_bot_wiring_and_no_delta_min():
    # Replica el wiring de run_bot: el lambda solo recibe delta_max y el
    # servicio lo llama sin delta_min (turno normal de conversación).
    state, counters = make_state(
        affinity={"42": {"points": 10, "last_interaction": NOW,
                          "last_gain": 0.0, "milestones": []}}
    )

    def _wiring(uid, delta, now=None, delta_max=None, delta_min=None):
        return A.apply_affinity_delta(
            state.affinity_entry(uid), delta, now or NOW,
            delta_max if delta_max is not None else A.AFFINITY_DELTA_MAX,
            delta_min if delta_min is not None else A.AFFINITY_DELTA_MIN,
        )

    state.apply_affinity_fn = _wiring

    applied = state.apply_affinity(42, 3, now=NOW, delta_max=5)

    assert applied == 3
    assert state.entry_points(42) == 13
    # El wiring personalizado persiste por su cuenta: no pasa por save_affinity.
    assert counters["affinity"] == 0
