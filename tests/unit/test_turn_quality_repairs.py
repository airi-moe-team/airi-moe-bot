"""Políticas unificadas de parseo y revisión del borrador."""

from __future__ import annotations

import asyncio
import json

from airi.services import conversation as conv_mod
from airi.services.conversation import (
    RESPONSE_SCHEMA,
    ConversationService,
    TurnContext,
)
from airi.domain.turn_quality import QualityIssue
from airi.testing import FakeLLM, FakeUser, llm_json, make_state

# --- reply_repeats_history ---------------------------------------------------

HIST = [{"role": "assistant", "content": llm_json(
    "¡Ah! Sí, ¡el canal! Qué susto me diste con el cane. Imagino que el "
    "saltamontes se cayó del techo o algo así."
)}]


def test_marca_copia_literal_de_un_turno_previo():
    nueva = (
        "¡Ah! Sí, ¡el canal! Qué susto me diste con el cane. Imagino que el "
        "saltamontes se cayó del techo o algo así, ¿no te parece?"
    )
    assert conv_mod.reply_repeats_history(nueva, HIST)


def test_marca_copia_aun_cambiando_el_cierre():
    nueva = (
        "¡Ah! Sí, ¡el canal! Qué susto me diste con el cane. Imagino que el "
        "saltamontes se cayó del techo y andaba por el pasillo del baño hoy."
    )
    assert conv_mod.reply_repeats_history(nueva, HIST)


def test_no_marca_respuesta_casual_distinta():
    nueva = (
        "*se encoge de hombros con una sonrisa* Bueno, cada quien tiene su "
        "ritmo. Al menos aquí nadie se aburre, eso es lo importante."
    )
    assert not conv_mod.reply_repeats_history(nueva, HIST)


def test_respuestas_cortas_no_se_marcan():
    assert not conv_mod.reply_repeats_history("¡Hola!", HIST)


def test_historial_vacio_nunca_marca():
    nueva = "Una respuesta tranquila, propia, con contenido suficiente largo."
    assert not conv_mod.reply_repeats_history(nueva, [])


def test_historial_sin_json_sigue_comparable():
    hist = [{
        "role": "assistant",
        "content": "Pues cada quien tiene su propio estilo de humor, está bien.",
    }]
    assert conv_mod.reply_repeats_history(
        "Pues cada quien tiene su propio estilo de humor, está bien y ya.",
        hist,
    )


# --- reparaciones a nivel de servicio ----------------------------------------

def _repair_service(replies):
    state, _ = make_state()
    llm = FakeLLM(replies=replies)
    service = ConversationService(llm=llm, state=state, clock=lambda: 1_000_000.0)
    return service, llm


def test_parse_repair_reutiliza_persona_y_regenera_por_sintoma():
    service, llm = _repair_service([llm_json("¡Aquí estoy de nuevo!")])
    calls = []
    messages = [
        {"role": "system", "content": "PERSONA AIRI"},
        {"role": "user", "content": "hola"},
    ]

    result = asyncio.run(
        service._repair(
            calls,
            "parse",
            messages=messages,
            schema=RESPONSE_SCHEMA,
            delta_max=5,
            max_tokens=None,
            symptom="empty",
        )
    )

    assert result is not None and result.accepted
    assert len(llm.calls) == 1
    request = llm.calls[0]["messages"]
    assert request[0] == messages[0]
    assert "vacía" in request[-1]["content"].lower()
    assert calls[0]["purpose"] == "parse_repair"


def test_quality_repair_anexa_el_borrador_y_pide_correccion_dirigida():
    draft = llm_json("Como modelo de lenguaje, me alegra hablar contigo.")
    revised = llm_json("Me alegra hablar contigo, de verdad.")
    service, llm = _repair_service([revised])
    calls = []
    issue = QualityIssue("ooc", "incoherent", "Como modelo de lenguaje", "deterministic")

    result = asyncio.run(
        service._repair(
            calls,
            "quality",
            messages=[{"role": "system", "content": "PERSONA AIRI"},
                      {"role": "user", "content": "hola"}],
            schema=RESPONSE_SCHEMA,
            delta_max=5,
            max_tokens=None,
            issues=[issue],
            draft=draft,
        )
    )

    assert len(llm.calls) == 1
    sent = llm.calls[0]["messages"]
    assert sent[-2] == {"role": "assistant", "content": draft}
    assert "Como modelo de lenguaje" in sent[-1]["content"]
    assert result is not None and result.accepted
    assert calls[0]["purpose"] == "quality_repair"


def test_quality_repair_descarta_reescritura_total_por_bajo_solapamiento():
    draft = llm_json(
        "Ayer caminamos por el parque y vimos un perro enorme junto a la fuente. "
        "Después nos sentamos cerca de los árboles, hablamos del viaje y miramos "
        "cómo el sol se escondía detrás de los edificios del centro."
    )
    service, _ = _repair_service([llm_json("Me encantan las películas de misterio.")])
    result = asyncio.run(
        service._repair(
            [],
            "quality",
            messages=[{"role": "system", "content": "PERSONA AIRI"}],
            schema=RESPONSE_SCHEMA,
            delta_max=5,
            max_tokens=None,
            issues=[QualityIssue("off_topic", "breaks_thread", "perro enorme", "review")],
            draft=draft,
        )
    )
    assert result is None


def test_quality_repair_respeta_stay_active_en_session_mode():
    from airi.domain.llm_output import SESSION_RESPONSE_SCHEMA

    service, llm = _repair_service([json.dumps({"reply": "Una corrección breve.", "stay_active": True})])
    result = asyncio.run(
        service._repair(
            [],
            "quality",
            messages=[{"role": "system", "content": "PERSONA AIRI"}],
            schema=SESSION_RESPONSE_SCHEMA,
            delta_max=5,
            max_tokens=None,
            session_mode=True,
            issues=[QualityIssue("ooc", "incoherent", "Como IA", "deterministic")],
            draft=llm_json("Como modelo de lenguaje, puedo responder.", stay_active=True),
        )
    )
    assert result is not None
    assert result.stay_active is True
    assert llm.calls[0]["messages"][-2]["role"] == "assistant"


def test_parse_repair_preserva_contrato_de_sesion():
    from airi.domain.llm_output import SESSION_RESPONSE_SCHEMA

    service, _ = _repair_service(
        [json.dumps({"reply": "Ahora sí.", "stay_active": False})]
    )
    result = asyncio.run(
        service._repair(
            [],
            "parse",
            messages=[{"role": "system", "content": "PERSONA AIRI"}],
            schema=SESSION_RESPONSE_SCHEMA,
            delta_max=5,
            max_tokens=None,
            session_mode=True,
            symptom="truncation",
        )
    )
    assert result is not None
    assert result.output.reply == "Ahora sí."
    assert result.stay_active is False
