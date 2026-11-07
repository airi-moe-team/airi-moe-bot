"""Textos narrativos puros de Airi (citas, confesión, regalos)."""

from __future__ import annotations

from airi.domain.constants import DATE_MAX_TURNS
from airi.persona import character_name

DATE_END_KEYWORDS = ("fin", "adios", "adiós", "hasta luego", "se acabo", "se acabó")

def confession_text(name):
    return (
        f"*{character_name()} respira hondo, con las mejillas encendidas, y te mira "
        "directamente a los ojos.*\n\n"
        f"«{name}... llevo un tiempo dándome cuenta de algo. Cada vez que hablas "
        "conmigo me late el corazón más deprisa, y cuando no estás te echo de "
        "menos. Ya no puedo seguir llamándote solo mi amigo.»\n\n"
        "*da un paso hacia ti y te ofrece la mano, temblando un poquito.*\n\n"
        f"«{name}, ¿quieres estar conmigo? ¿Quieres ser mi pareja?»\n\n"
        f"💗 ¡{character_name()} ha elegido! A partir de ahora **sois novios**. 💗"
    )

def gift_reaction(item, effect):
    if effect > 0:
        return (
            f"*{character_name()} abre los ojos con una sonrisa y se sonroja.*\n"
            f"«¡Uh... {item}! Es justo lo que me gusta... ¿cómo lo sabías? "
            "Gracias~»"
        )
    if effect < 0:
        return (
            f"*{character_name()} mira {item}, luego a ti, y arquea una ceja.*\n"
            "«Mmh... no sé si es lo mío, pero... se agradece el detalle.»"
        )
    return (
        f"*{character_name()} observa {item} con una sonrisa leve.*\n"
        "«Gracias... aunque creo que ya tienes algo parecido, ¿no?»"
    )

def date_intro(scene):
    return (
        f"*{character_name()} se ilumina al aceptar.*\n«¿En serio? ¡Vale! Entonces... {scene}. "
        "Qué nervios...»\n\n*(Comienza la cita. Habla con ella y deja que el "
        f"momento fluya: durará unos {DATE_MAX_TURNS} turnos. Si las cosas "
        "se tuercen tendrás una última oportunidad para reconducirlo.)*"
    )

DATE_FINAL_TEXTS = {
    "ending": (
        "*La cita llega a su fin de forma natural.*\n"
        "«Ha sido... un momento muy bonito. *se sonroja* Me gustaría repetirlo "
        "pronto, ¿vale?»"
    ),
    "recovered": (
        f"*{character_name()} te mira con los ojos brillantes, como si hubiera pasado un miedo "
        "enorme.*\n«Pensaba que la habíamos estropeado... pero me has demostrado "
        "que te importo. *te aprieta la mano* Gracias por no rendirte conmigo.»"
    ),
    "partial_recovery": (
        "*La cita termina con una sonrisa frágil.*\n«No ha sido perfecto, pero... "
        "me has dado algo en qué pensar. *te mira de reojo* Quizá necesitemos otra "
        "oportunidad, despacio.»"
    ),
    "failed_last_chance": (
        f"*{character_name()} aparta la mirada y suspira.*\n«Creo que... hoy no era el día. "
        "Dejémoslo aquí, ¿vale? Necesito pensar.»"
    ),
}


def date_final_text(event):
    return DATE_FINAL_TEXTS.get(event, DATE_FINAL_TEXTS["ending"])


# Texto de la crisis (se envía al entrar en última oportunidad).
DATE_CRISIS_TEXT = (
    f"*Algo se tuerce y {character_name()} se queda callada un momento.*\n"
    "«Ehh... espera. No sé si esto está yendo bien. *te mira, seria* "
    "Dame un momento... ¿puedes darme UNA razón para creer que te "
    "importo de verdad?»"
)

# Texto que se envía cuando la cita se queda sin tiempo para la pregunta.
DATE_QUESTION_MISSED_TEXT = (
    f"*{character_name()} mira el reloj y se le escapa un suspiro.*\n"
    "«Vaya... se me ha pasado el momento de preguntarte algo importante. "
    "La próxima vez, ¿vale?»"
)

def date_question_result_note(win, delta):
    """Nota interna para el turno de reacción tras responder la pregunta.

    El motor ya aplicó el cambio de afinidad; esto solo le dice a Airi cómo
    reaccionar sin volver a mover la afinidad ni repetir la pregunta.
    """
    sign = f"{delta:+d}"
    if win:
        return (
            "ACABA DE RESPONDER TU PREGUNTA y su respuesta te ha llegado de "
            f"verdad (afinidad {sign}, ya aplicada por el sistema). Reacciona "
            "emocionada y cálida, con una frase breve, sin repetir la pregunta "
            "ni volver a mover la afinidad."
        )
    if delta <= 0:
        return (
            "ACABA DE RESPONDER TU PREGUNTA y su respuesta te ha dolido "
            f"(afinidad {sign}, ya aplicada por el sistema). Reacciona dolida o "
            "decepcionada, con una frase breve; no repitas la pregunta ni "
            "vuelvas a mover la afinidad."
        )
    return (
        "ACABA DE RESPONDER TU PREGUNTA y su respuesta te ha dejado "
        f"indecisa (afinidad {sign}, ya aplicada por el sistema). Reacciona con "
        "una frase breve; no repitas la pregunta ni vuelvas a mover la afinidad."
    )
