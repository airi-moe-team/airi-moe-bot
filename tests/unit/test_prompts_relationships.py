"""Contrato del prompt: Airi no persigue pareja y solo cambia con evidencia."""

from __future__ import annotations

from airi.domain.prompts import (
    GIF_DECISION_PROMPT,
    SYSTEM_PROMPT,
    affinity_prompt_section,
    date_context_section,
    relationship_status_section,
    romantic_relationship_section,
)


def test_system_prompt_does_not_make_romance_the_goal():
    lowered = SYSTEM_PROMPT.lower()
    assert "no" in lowered and "conseguir pareja" in lowered
    assert "amistad" in lowered
    # La "curiosidad" dejó de nombrarse como regla del prompt (riesgo de
    # encadenar preguntas en cada cierre); vive como rasgo del self model.
    assert "no estás buscando" in lowered or "no tienes como objetivo" in lowered


def test_single_status_does_not_present_her_as_seeking_a_partner():
    text = relationship_status_section(
        {"winner_id": None}, {}, user_id=1, display_name="Ana", now=0
    )
    assert "abierta a conocer a alguien" not in text
    assert "No estás buscando pareja" in text
    assert "no tienes pareja" in text.lower()


def test_romantic_section_shows_stage_and_allowed_evidence_only():
    record = {
        "stage": "interest",
        "history": [
            {
                "id": "r1",
                "from": "curiosity",
                "to": "interest",
                "evidence_kind": "support",
                "reason": "Me apoyó",
                "evidence_refs": ["turn:1:10"],
                "evidence_summary": "Me acompañó cuando estaba triste.",
                "season": 1,
                "created_at": 10.0,
            }
        ],
        "pending_proposal": None,
    }
    text = romantic_relationship_section(
        {"stage": "interest", "history": record["history"], "pending": None,
         "allowed_refs": ["turn:1:10", "ev:r1", "turn:1:20"],
         "is_partner": False},
        "Ana",
    )
    assert "interés" in text.lower()
    assert "Me acompañó cuando estaba triste." in text
    assert "turn:1:20" in text
    assert "ev:r1" in text
    assert "no inventes" in text.lower()


def test_neutral_romantic_section_says_there_is_no_romantic_feeling():
    text = romantic_relationship_section(
        {"stage": "none", "history": [], "pending": None,
         "allowed_refs": ["turn:1:20"], "is_partner": False},
        "Ana",
    )
    assert "ninguna" in text.lower()
    assert "amistad" in text.lower()


def test_affinity_tones_stop_implying_romance():
    for level in ("Cercana", "Muy cercana", "Inseparables"):
        text = affinity_prompt_section(90, level, "Ana")
        assert "etapa afectiva" in text
        assert "afinidad" in text


def test_output_contract_documents_the_new_objects():
    assert "romantic_update" in GIF_DECISION_PROMPT
    assert "relationship_action" in GIF_DECISION_PROMPT
    assert "evidence_refs" in GIF_DECISION_PROMPT
    assert "No inventes" in GIF_DECISION_PROMPT


def test_date_context_is_optional_and_never_forced():
    session = {
        "scene": "un paseo",
        "state": "active",
        "turns": 4,
        "question_used": False,
        "question_pending": False,
        "question": None,
    }
    text = date_context_section(session)
    assert "ÚLTIMA oportunidad" not in text
    assert "MOMENTO DE LA PREGUNTA" not in text
    assert "puedes" in text.lower()
