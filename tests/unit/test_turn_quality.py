"""Checks puros de calidad del turno (artefactos, OOC, repetición, revisor)."""

from __future__ import annotations

import json

from airi.domain.turn_quality import (
    QualityIssue,
    is_out_of_character,
    merge_issues,
    parse_review,
    quality_issues,
    reply_repeats_history,
    token_overlap,
)

# --- is_out_of_character ----------------------------------------------------


def test_detecta_frases_de_asistente():
    assert is_out_of_character("Como modelo de lenguaje, no puedo ayudarte.")
    assert is_out_of_character("Hablando como una IA, diría que...")
    assert is_out_of_character("Como asistente virtual, debo aclarar algo.")


def test_no_marca_conversacion_normal():
    assert is_out_of_character("Soy Airi y me encanta el té frío.") is None
    assert is_out_of_character("") is None
    assert is_out_of_character(None) is None


# --- token_overlap ----------------------------------------------------------


def test_solapamiento_identico_es_uno():
    assert token_overlap("hola qué tal", "hola qué tal") == 1.0


def test_solapamiento_de_reescritura_total_es_cero():
    assert token_overlap("hola qué tal", "buenas noches amigo") == 0.0


def test_solapamiento_ignora_los_fragmentos_marcados():
    draft = "me voy a dormir porque mañana madrugo"
    revised = "mañana madrugo"
    assert token_overlap(draft, revised, ignored=["me voy a dormir"]) >= 0.60


def test_solapamiento_con_revision_vacia_es_cero():
    assert token_overlap("hola qué tal", "") == 0.0
    assert token_overlap("", "hola") == 1.0


# --- parse_review -----------------------------------------------------------


def _review(**overrides):
    payload = {
        "on_topic": True,
        "right_addressee": True,
        "coherent": True,
        "issues": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_parse_review_valido_sin_issues():
    result = parse_review(_review())
    assert result.valid is True
    assert result.issues == ()
    assert result.on_topic is True


def test_parse_review_invalido_no_lanza():
    assert parse_review("no es json").valid is False
    assert parse_review("").valid is False
    assert parse_review(None).valid is False
    assert parse_review(json.dumps({"on_topic": True})).valid is False


def test_parse_review_descarta_issue_sin_evidencia():
    raw = _review(
        on_topic=False,
        issues=[
            {"kind": "off_topic", "impact": "breaks_thread", "evidence": ""},
            {"kind": "off_topic", "impact": "breaks_thread", "evidence": "me voy"},
        ],
    )
    result = parse_review(raw)
    assert len(result.issues) == 1
    assert result.issues[0].evidence == "me voy"
    assert result.issues[0].origin == "review"


def test_parse_review_descarta_kind_o_impact_invalidos():
    raw = _review(
        issues=[
            {"kind": "inventado", "impact": "breaks_thread", "evidence": "x"},
            {"kind": "nonsense", "impact": "inventado", "evidence": "y"},
        ],
    )
    assert parse_review(raw).issues == ()


def test_parse_review_con_borrador_exige_evidencia_literal():
    raw = _review(
        issues=[
            {"kind": "off_topic", "impact": "breaks_thread", "evidence": "no aparece"},
            {"kind": "off_topic", "impact": "breaks_thread", "evidence": "frase literal"},
        ]
    )
    result = parse_review(raw, draft="Esta es una frase literal del borrador.")
    assert [issue.evidence for issue in result.issues] == ["frase literal"]


# --- quality_issues ---------------------------------------------------------


def test_quality_issues_marca_ooc():
    issues = quality_issues("Como modelo de lenguaje, no puedo.", [])
    assert [i.kind for i in issues] == ["ooc"]
    assert issues[0].impact == "incoherent"
    assert issues[0].origin == "deterministic"


def test_quality_issues_marca_repeticion_del_propio_turno():
    history = [
        {
            "role": "assistant",
            "content": "¡Ah! Sí, el canal. Qué susto me diste con el cane, "
            "imagino que el saltamontes se cayó del techo.",
        }
    ]
    reply = (
        "¡Ah! Sí, el canal. Qué susto me diste con el cane, imagino que el "
        "saltamontes se cayó del techo."
    )
    assert [i.kind for i in quality_issues(reply, history)] == ["repeat"]


def test_quality_issues_marca_eco_de_un_usuario():
    history = [
        {
            "role": "user",
            "content": "ayer estuve en la playa con mis amigos y nos quedamos "
            "hasta que anocheció del todo",
        }
    ]
    reply = (
        "ayer estuve en la playa con mis amigos y nos quedamos hasta que "
        "anocheció del todo, qué bonito"
    )
    assert [i.kind for i in quality_issues(reply, history)] == ["repeat_user"]


def test_quality_issues_marca_cierre_interrogativo_repetido():
    issues = quality_issues(
        "Pues sí, fue un día raro. ¿Y tú qué crees?",
        [],
        previous_closed_with_question=True,
    )
    assert [i.kind for i in issues] == ["question_close"]


def test_quality_issues_no_marca_cierre_si_no_hubiera_pregunta_previa():
    issues = quality_issues(
        "Pues sí, fue un día raro. ¿Y tú qué crees?",
        [],
        previous_closed_with_question=False,
    )
    assert issues == []


# --- reply_repeats_history --------------------------------------------------


def test_reply_repeats_history_ignora_usuarios_por_defecto():
    history = [
        {
            "role": "user",
            "content": "ayer estuve en la playa con mis amigos y nos quedamos "
            "hasta que anocheció del todo",
        }
    ]
    reply = (
        "ayer estuve en la playa con mis amigos y nos quedamos hasta que "
        "anocheció del todo, qué bonito"
    )
    assert reply_repeats_history(reply, history) is False
    assert reply_repeats_history(reply, history, include_user=True) is True


# --- merge_issues -----------------------------------------------------------


def test_merge_issues_elimina_duplicados_por_tipo():
    a = QualityIssue("ooc", "incoherent", "evidencia", "deterministic")
    b = QualityIssue("ooc", "incoherent", "otra", "review")
    c = QualityIssue("off_topic", "breaks_thread", "x", "review")
    assert merge_issues([a], [b, c]) == (a, c)
