import asyncio
import json

from airi.evaluation.web_search import (
    WebSearchScenario,
    generate_web_search_records,
    judge_web_search_records,
)
from airi.ports.web_search import WebResult, WebSearchNotes
from airi.testing import FakeLLM, llm_json


def run(coro):
    return asyncio.run(coro)


def test_live_eval_records_model_decision_and_controlled_search_results():
    scenarios = (
        WebSearchScenario(
            id="check_fact",
            description="Comprueba un dato y reacciona a las notas.",
            user_message="¿A cuánto está el precio?",
            expected_search=True,
            notes=WebSearchNotes((WebResult("Precio", "Cuesta 42 euros."),)),
        ),
        WebSearchScenario(
            id="opinion",
            description="No buscar para una opinión personal.",
            user_message="¿Te gusta el café?",
            expected_search=False,
            notes=None,
        ),
    )
    tool_calls = [
        [{"name": "buscar_web", "arguments": {
            "query": "precio actual", "motivo": "me dio curiosidad",
        }}],
        [],
    ]
    llm = FakeLLM(
        tool_calls=tool_calls,
        replies=[llm_json("Vaya, 42 euros me parece caro~"), llm_json("Sí, me gusta~")],
    )

    records = run(generate_web_search_records(llm=llm, scenarios=scenarios))

    assert records[0]["actual_search"] is True
    assert records[0]["query"] == "precio actual"
    assert records[0]["motivo"] == "me dio curiosidad"
    assert records[0]["search_status"] == "results"
    assert "42 euros" in records[0]["reply"]
    assert records[1]["actual_search"] is False
    assert records[1]["search_status"] == "not_requested"


def test_semantic_judge_adds_phrase_agnostic_labels_to_records():
    record = {
        "scenario": "contradictory_notes",
        "user": "¿En qué año fue?",
        "reply": "No me queda claro, vi dos años distintos.",
        "actual_search": True,
        "search_results": [],
    }
    judgment = {
        "query_resolved": "yes",
        "motivation_integrated": "yes",
        "personal_reaction": "yes",
        "report_style": "no",
        "uncertainty_calibrated": "yes",
        "unsupported_specific_claim": "no",
        "canned_phrase": "no",
        "rationale": "Expresa la contradicción con una duda propia.",
    }
    llm = FakeLLM(replies=[json.dumps(judgment, ensure_ascii=False)])

    result = run(judge_web_search_records(llm, [record]))

    assert result[0]["semantic_judgment"]["uncertainty_calibrated"] == "yes"
    judge_system = llm.calls[0]["messages"][0]["content"]
    assert "Juzga el sentido y la función" in judge_system
    assert "no frases literales" in judge_system
    assert "query_resolved" in judge_system
    assert llm.calls[0]["strict_schema"] is True


def test_live_eval_passes_active_task_goal_to_web_decision():
    scenario = WebSearchScenario(
        id="task_goal",
        description="Busca según el objetivo acordado, no por significado aislado.",
        user_message="La siguiente frase es Moantai.",
        expected_search=True,
        notes=WebSearchNotes((WebResult("Digimon", "Moumantai se asocia con Terriermon."),)),
        kind="spectator",
        task_context={
            "goal": "Identificar el anime de cada frase",
            "constraints": ["cinco frases", "dos vidas"],
            "progress": "La primera era Evangelion",
            "next_step": "Resolver la segunda",
        },
    )
    llm = FakeLLM(
        tool_calls=[[
            {"name": "buscar_web", "arguments": {
                "query": "Moantai anime frase", "motivo": "quiero identificar el anime",
            }}
        ]],
        replies=[llm_json("Creo que es Digimon.", stay_active=True)],
    )

    records = run(generate_web_search_records(llm=llm, scenarios=(scenario,)))

    assert records[0]["actual_search"] is True
    assert records[0]["allow_web"] is True
    assert records[0]["task_context"]["goal"] == "Identificar el anime de cada frase"
    assert "Identificar el anime de cada frase" in llm.decision_calls[0]["messages"][-1]["content"]
