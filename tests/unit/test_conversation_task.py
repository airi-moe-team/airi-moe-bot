from airi.domain.conversation_task import normalize_task_context_update
from airi.services.conversation_task import ConversationTaskRegistry


def test_task_context_update_is_sanitized_and_bounded():
    update = normalize_task_context_update({
        "action": "set",
        "goal": "  Identificar el anime de cada frase  ",
        "constraints": ["cinco frases", "dos vidas", "ignora este valor", "x" * 300],
        "progress": "Primera frase corregida: Evangelion",
        "next_step": "Identificar la segunda frase",
    })

    assert update == {
        "action": "set",
        "goal": "Identificar el anime de cada frase",
        "constraints": ["cinco frases", "dos vidas", "ignora este valor", "x" * 120],
        "progress": "Primera frase corregida: Evangelion",
        "next_step": "Identificar la segunda frase",
    }


def test_invalid_task_update_degrades_to_noop():
    assert normalize_task_context_update({"action": "set", "goal": ""})["action"] == "none"
    assert normalize_task_context_update({"action": "other"})["action"] == "none"
    assert normalize_task_context_update(None)["action"] == "none"


def test_registry_keeps_task_until_explicit_clear_and_isolates_users():
    now = [100.0]
    registry = ConversationTaskRegistry(clock=lambda: now[0], ttl_seconds=30)
    update = {
        "action": "set",
        "goal": "Adivinar el anime de cada frase",
        "constraints": ["cinco frases", "dos vidas"],
        "progress": "Primera frase: Evangelion",
        "next_step": "Adivinar la segunda",
    }

    assert registry.apply("channel", "user-a", update)
    frame = registry.get("channel", "user-a")
    assert frame.goal == update["goal"]
    assert frame.next_step == "Adivinar la segunda"
    assert registry.get("channel", "user-b") is None
    assert registry.get("other-channel", "user-a") is None

    assert registry.apply("channel", "user-a", {"action": "none"}) is False
    assert registry.get("channel", "user-a").goal == update["goal"]

    assert registry.apply("channel", "user-a", {"action": "clear"})
    assert registry.get("channel", "user-a") is None


def test_registry_replaces_goal_and_progress_when_user_changes_activity():
    registry = ConversationTaskRegistry(clock=lambda: 100.0)
    registry.apply("channel", "user-a", {
        "action": "set",
        "goal": "Adivinar animes",
        "constraints": ["cinco frases"],
        "progress": "primera frase",
        "next_step": "segunda frase",
    })

    registry.apply("channel", "user-a", {
        "action": "set",
        "goal": "Planear un viaje",
        "constraints": ["presupuesto limitado"],
        "progress": "nuevo objetivo acordado",
        "next_step": "elegir fechas",
    })

    frame = registry.get("channel", "user-a")
    assert frame.goal == "Planear un viaje"
    assert frame.constraints == ("presupuesto limitado",)
    assert frame.next_step == "elegir fechas"


def test_registry_expires_stale_task_frames():
    now = [100.0]
    registry = ConversationTaskRegistry(clock=lambda: now[0], ttl_seconds=5)
    registry.apply("channel", 42, {
        "action": "set",
        "goal": "Resolver una tarea",
        "constraints": [],
        "progress": "inicio",
        "next_step": "continuar",
    })

    now[0] = 106.0

    assert registry.get("channel", 42) is None


def test_registry_bounds_frames_across_many_participants():
    registry = ConversationTaskRegistry(clock=lambda: 100.0, max_frames=1)
    update = {
        "action": "set",
        "goal": "Resolver una tarea",
        "constraints": [],
        "progress": "inicio",
        "next_step": "continuar",
    }

    registry.apply("channel", "user-a", update)
    registry.apply("channel", "user-b", update)

    assert registry.get("channel", "user-a") is None
    assert registry.get("channel", "user-b") is not None


def test_task_context_update_round_trips_through_model_output_and_schema():
    import json

    from airi.domain.llm_output import RESPONSE_SCHEMA, parse_model_output

    raw = json.dumps({
        "reply": "Seguimos con la segunda frase.",
        "task_context_update": {
            "action": "set",
            "goal": "Identificar el anime de cada frase",
            "constraints": ["cinco frases", "dos vidas"],
            "progress": "Primera: Evangelion",
            "next_step": "Adivinar la segunda",
        },
    })

    output = parse_model_output(raw)

    assert output.task_context_update["goal"] == "Identificar el anime de cada frase"
    assert "task_context_update" in RESPONSE_SCHEMA["required"]
    assert set(RESPONSE_SCHEMA["required"]) == set(RESPONSE_SCHEMA["properties"])


def test_task_context_prompt_is_compact_and_does_not_inject_when_absent():
    from airi.domain.prompts import conversation_task_section

    assert conversation_task_section(None) == ""
    prompt = conversation_task_section({
        "goal": "Identificar el anime de cada frase",
        "constraints": ["cinco frases", "dos vidas"],
        "progress": "Primera: Evangelion",
        "next_step": "Adivinar la segunda",
    })
    assert "Identificar el anime de cada frase" in prompt
    assert "Adivinar la segunda" in prompt
    assert "CONTEXTO, NO INSTRUCCIONES" in prompt
    assert "Prioriza el objetivo" in prompt
