"""Detección de intención de búsqueda web (explícita, corrección, duda)."""

from __future__ import annotations

from airi.domain.web import (
    detect_search_intent,
    needs_web_search,
    recent_topic_terms,
    web_results_relevant,
)


def _assistant(reply):
    return {"role": "assistant", "content": f'{{"reply": "{reply}"}}'}


def _user(text):
    return {"role": "user", "content": text}


# ---------------------------------------------------------------------------
# Petición explícita
# ---------------------------------------------------------------------------


def test_explicit_con_typo_y_verbos_compuestos():
    intent = detect_search_intent(
        "uhm creo que  te estas confundiendo puedes buscarlo por inernet"
    )
    assert intent == "explicit"


def test_explicit_buscalo_en_internet():
    assert detect_search_intent("búscalo en internet") == "explicit"
    assert detect_search_intent("buscalo en inernet") == "explicit"


def test_explicit_imperativos_de_verificacion():
    assert detect_search_intent("compruébalo") == "explicit"
    assert detect_search_intent("verifícalo porfa") == "explicit"
    assert detect_search_intent("averigua quién era") == "explicit"


def test_explicit_buscame_con_mencion_web():
    assert (
        detect_search_intent("búscame en internet el precio de bitcoin") == "explicit"
    )


def test_no_explicit_si_es_un_regalo():
    assert detect_search_intent("búscame un regalo bonito") is None


def test_no_explicit_si_solo_menciona_internet():
    assert detect_search_intent("lo vi por internet") is None


def test_explicit_por_frescura_sin_verbo():
    assert detect_search_intent("últimas noticias de Frieren") == "explicit"
    assert detect_search_intent("precio actual del bitcoin") == "explicit"
    assert detect_search_intent("estado actual de la serie") == "explicit"


# ---------------------------------------------------------------------------
# Corrección factual
# ---------------------------------------------------------------------------


def test_correction_con_nombre_propio():
    assert detect_search_intent("Eisen no era el enano?") == "correction"


def test_correction_apoyada_en_el_historial():
    history = [
        _user("Eisen no era el enano?"),
        _assistant("Eisen es el elfo, no el enano"),
        _user("te estás confundiendo"),
    ]
    assert (
        detect_search_intent("te estás confundiendo", history=history)
        == "correction"
    )


def test_correction_con_ano():
    assert detect_search_intent("no fue en 2024") == "correction"


def test_correction_sin_marcador_factual_no_dispara():
    assert detect_search_intent("eres tonta, te confundes") is None


def test_no_correction_en_charla_normal():
    assert detect_search_intent("no es que no me guste, pero prefiero el té") is None


def test_cualquier_usuario_cuenta_como_marcador_factual():
    assert detect_search_intent("Mathias no era el enano?") == "correction"


def test_el_nombre_del_interlocutor_no_cuenta_como_marcador():
    assert (
        detect_search_intent(
            "Mathias no era el enano?", exclude_names=("Mathias",)
        )
        is None
    )


def test_el_nombre_del_bot_no_cuenta_como_marcador():
    assert (
        detect_search_intent(
            "Airi no era el enano?", exclude_names=("Airi",)
        )
        is None
    )


def test_excluir_un_nombre_no_oculta_otros_marcadores():
    assert (
        detect_search_intent(
            "Mathias no era el enano de Frieren?",
            exclude_names=("Mathias",),
        )
        == "correction"
    )


# ---------------------------------------------------------------------------
# Incertidumbre + confirmación
# ---------------------------------------------------------------------------


def test_uncertainty_tras_respuesta_dudosa():
    history = [
        _user("sabes su nombre?"),
        _assistant("Creo que se llamaba Eisen"),
    ]
    assert (
        detect_search_intent("sabes su nombre?", history=history)
        == "uncertainty"
    )


def test_question_factual_sobre_un_tema_ya_mencionado():
    history = [_assistant("Frieren y Stark son geniales")]
    assert detect_search_intent("sabes su nombre?", history=history) == "question"


def test_question_sin_tema_factual_no_dispara():
    history = [_assistant("Qué día tan bonito")]
    assert detect_search_intent("sabes su nombre?", history=history) is None


def test_uncertainty_con_confirmacion_explicita():
    history = [_assistant("No recuerdo el nombre del héroe, Himmel creo")]
    assert (
        detect_search_intent("¿seguro?", history=history) == "uncertainty"
    )


# ---------------------------------------------------------------------------
# Compatibilidad y espectador
# ---------------------------------------------------------------------------


def test_needs_web_search_mantiene_la_firma_simple():
    assert needs_web_search("búscame en internet algo") is True
    assert needs_web_search("me gusta Frieren") is False


def test_proactivo_sin_texto_no_dispara():
    history = [_assistant("Creo que se llamaba Eisen")]
    assert detect_search_intent("", history=history) is None


def test_spectator_usa_el_snapshot_para_el_marcador_factual():
    snapshot = (
        {
            "author_name": "KOKODA",
            "content": "Eisen no era el enano?",
            "message_id": "1",
        },
    )
    assert (
        detect_search_intent(
            "te estás confundiendo", snapshot=snapshot
        )
        == "correction"
    )


# ---------------------------------------------------------------------------
# Ancla de tema y relevancia de resultados
# ---------------------------------------------------------------------------


def test_recent_topic_terms_extrae_entidades_y_excluye_nombres():
    terms = recent_topic_terms(
        [
            "Airi dijo que Frieren era su anime favorito",
            "KOKODA preguntó por Stark y Eisen",
        ],
        exclude_names=("Airi", "KOKODA"),
    )
    assert "Frieren" in terms
    assert "Stark" in terms
    assert "Eisen" in terms
    assert "Airi" not in terms
    assert "KOKODA" not in terms


def test_recent_topic_terms_prioriza_lo_mas_reciente():
    terms = recent_topic_terms(
        ["Primero Frieren", "Luego Stark", "Ahora Eisen"]
    )
    assert terms[:3] == ["Eisen", "Stark", "Frieren"]


def test_resultados_relevantes_si_cubren_la_query():
    assert (
        web_results_relevant(
            "Fuente 1: Frieren\nResumen: el héroe era Himmel",
            "Frieren héroe",
            ["Eisen"],
        )
        is True
    )


def test_resultados_irrelevantes_si_no_cubren_la_query():
    assert (
        web_results_relevant(
            "Fuente 1: Re:Zero\nResumen: otro anime",
            "Frieren héroe",
            ["Frieren"],
        )
        is False
    )


def test_sin_entidades_en_la_query_usa_el_ancla_del_tema():
    assert (
        web_results_relevant(
            "Fuente 1: Re:Zero\nResumen: otro anime",
            "cuál es el héroe correcto",
            ["Frieren"],
        )
        is False
    )
