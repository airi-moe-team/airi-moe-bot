"""Reparaciones de calidad del turno: respuesta vacía y copia literal.

Cubre `reply_repeats_history` y el gesto de `_repair_regenerate` a nivel de
servicio (FakeLLM con dos respuestas: la defectuosa y la reparada).
"""

from __future__ import annotations

import asyncio
import json

from airi.services import conversation as conv_mod
from airi.services.conversation import (
    EMPTY_REPLY_REPAIR_PROMPT,
    REPEAT_REPAIR_PROMPT,
    ConversationService,
    TurnContext,
)
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

def _last_note(llm):
    """Contenido del último mensaje de usuario (el aviso de reparación)."""
    return llm.calls[-1]["messages"][-1]["content"]


def _run_turn(state, llm, message):
    user = FakeUser(42, "David")
    svc = ConversationService(llm=llm, state=state, clock=lambda: 1_000_000.0)
    asyncio.run(svc.run_turn(user, [(user, message)], TurnContext()))


def test_respuesta_vacia_se_reintenta_una_vez():
    state, _ = make_state()
    # Primera llamada: JSON con reply vacío; segunda: repair con contenido.
    empty = json.dumps({"reply": "", "gif": "shy"})
    llm = FakeLLM(replies=[empty, llm_json("¡Aquí estoy de nuevo, con ganas!")])

    _run_turn(state, llm, "hola, ¿sigues ahí?")

    assert len(llm.calls) == 2
    assert _last_note(llm) == EMPTY_REPLY_REPAIR_PROMPT


def test_copia_literal_se_regenera_con_aviso():
    state, _ = make_state()
    state.histories[0] = [
        {"role": "user", "content": "hola", "author_id": "42", "author_name": "David"},
        HIST[0],
    ]
    copia = llm_json(
        "¡Ah! Sí, ¡el canal! Qué susto me diste con el cane. Imagino que el "
        "saltamontes se cayó del techo o algo así, ¿verdad?"
    )
    nueva = llm_json(
        "*se encoge de hombros* Bueno, me has pillado: aquí somos raritos. "
        "Prefiero bromea a silencios incómodos, la verdad."
    )
    llm = FakeLLM(replies=[copia, nueva])

    _run_turn(state, llm, "no entiendo su humor son 2 raritos en el chat")

    assert len(llm.calls) == 2
    assert _last_note(llm) == REPEAT_REPAIR_PROMPT
