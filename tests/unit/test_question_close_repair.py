"""Red de seguridad anti-interrogatorio en charla casual.

Cubre el recorte determinista de la oración interrogativa final y el gesto del
repair: solo se activa si el turno anterior de Airi cerró con pregunta y la
respuesta nueva vuelve a cerrar igual. Las citas quedan fuera (ahí la
conversación puede preguntar).
"""

from airi.domain.prompts import last_assistant_reply_ended_with_question
from airi.services.conversation import (
    strip_trailing_question,
    strip_trailing_questions,
)

# --- strip_trailing_question ------------------------------------------------

def test_recorta_la_oracion_interrogativa_final():
    texto = "Bueno, cada quien tiene su humor. ¿Y tú qué opinas?"
    assert strip_trailing_question(texto) == "Bueno, cada quien tiene su humor."


def test_recorta_pregunta_retorica_tras_asterisco():
    texto = "*se encoge de hombros* A veces soy rara, ¿verdad?"
    assert strip_trailing_question(texto) == "*se encoge de hombros* A veces soy rara,"


def test_recorta_tras_exclamacion():
    texto = "¡Qué va! ¿Seguro?"
    assert strip_trailing_question(texto) == "¡Qué va!"


def test_pregunta_sin_apertura_no_deja_vacio():
    # Sin '¿' ni delimitador previo: se respeta la respuesta tal cual.
    texto = "¿Y tú qué opinas?"
    assert strip_trailing_question(texto) == texto


def test_no_toca_respuesta_que_no_cierra_en_pregunta():
    texto = "Bueno, cada quien tiene su humor. Yo me divierto igual."
    assert strip_trailing_question(texto) == texto


def test_no_vacia_una_respuesta_que_es_solo_pregunta():
    texto = "¿Y tú qué opinas?"
    assert strip_trailing_question(texto) == texto


def test_tolerante_a_vacios():
    assert strip_trailing_question("") == ""
    assert strip_trailing_question(None) is None


def test_recorta_varias_preguntas_encadenadas():
    texto = "Prefiero el té. ¿Y tú qué? ¿Prefieres café o té?"
    assert strip_trailing_questions(texto) == "Prefiero el té."


def test_strip_trailing_questions_no_vacia_una_respuesta_de_solo_preguntas():
    assert strip_trailing_questions("¿Y tú?") == "¿Y tú?"


# --- last_assistant_reply_ended_with_question -------------------------------

def _hist(reply):
    return [{"role": "assistant", "content": reply}]


def test_detecta_cierre_con_pregunta_en_json_de_historial():
    import json

    raw = json.dumps({"reply": "¿Todo bien?", "gif": "shy"})
    assert last_assistant_reply_ended_with_question(_hist(raw))


def test_sin_pregunta_previa_no_dispara():
    assert not last_assistant_reply_ended_with_question([])
    assert not last_assistant_reply_ended_with_question(
        _hist("¡Hola! Qué gusto verte.")
    )
