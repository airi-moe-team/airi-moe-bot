"""Afirmaciones narrativas de Airi sobre su estado (marcha y despedida).

El texto que Airi publica y su decisión estructurada (`disconnect.leave`)
deben decir lo mismo. Si el mensaje dice «me voy a dormir» y la decisión es
quedarse, Airi está fingiendo una desconexión que no ocurre: es exactamente
la mentira que esta feature elimina.

Este módulo es PURO (sin I/O) y lo usan dos capas:

- el dominio, para validar la salida del modelo y pedir su reparación;
- el evaluador narrativo, para medir la coherencia con el modelo real.
"""

from __future__ import annotations

import re

#: Frases en primera persona que ponen a Airi en marcha AHORA.
LEAVING_CLAIM_RE = re.compile(
    r"\b(?:me\s+voy|me\s+marcho|me\s+duermo|me\s+acuesto|"
    r"me\s+estoy\s+durmiendo|me\s+retiro|apago)\b",
    re.IGNORECASE,
)

#: «Desconectar» solo cuenta si se refiere a la marcha de AHORA: «a veces me
#: desconecto de golpe» describe una costumbre, no una decisión de este turno.
LEAVING_NOW_RE = re.compile(
    r"(?:me\s+desconecto|me\s+desconectar|desconectarme|desconectar)\b"
    r"(?:\s+\w+){0,3}\s*(?:ahora|ya)\b"
    r"|\b(?:ahora|ya)\b(?:\s+\w+){0,3}\s*"
    r"(?:me\s+desconecto|me\s+desconectar|desconectarme)\b"
    r"|\b(?:voy\s+a|vamos\s+a)\s+desconectar(?:me)?\b"
    r"|\bme\s+voy\s+a\s+(?:desconectar|quedar|irme)\b"
    r"|\bcierro\s+la\s+conexi[oó]n\b",
    re.IGNORECASE,
)

#: Negaciones que invalidan una afirmación de marcha («no me voy», «no pienso…»).
NEGATION_RE = re.compile(
    r"\bno\b(?:\s+\w+){0,2}\s*$", re.IGNORECASE
)

#: Marcas de despedida (no implican marcharse: pueden ser «nos vemos luego»).
FAREWELL_RE = re.compile(
    r"\b(?:hasta\s+luego|nos\s+vemos|adi[oó]s|hasta\s+ma[ñn]ana|"
    r"hasta\s+pronto|buenas\s+noches|hasta\s+la\s+vista)\b",
    re.IGNORECASE,
)


def mentions_farewell(text) -> bool:
    """True si el texto se despide (sin decir necesariamente que se va)."""
    return bool(FAREWELL_RE.search(str(text or "")))


def mentions_leaving(text) -> bool:
    """True si el texto afirma que Airi se va AHORA (sin negar que se queda)."""
    text = str(text or "")
    for pattern in (LEAVING_CLAIM_RE, LEAVING_NOW_RE):
        for match in pattern.finditer(text):
            before = text[max(0, match.start() - 24):match.start()]
            if NEGATION_RE.search(before):
                continue
            return True
    return False


def disconnect_claim_problem(reply, leave) -> str | None:
    """Problema de contrato entre lo que dice Airi y lo que decide.

    Devuelve el texto del problema o `None` si ambos coinciden.
    """
    claims_leaving = mentions_leaving(reply)
    if claims_leaving and not leave:
        return (
            "el mensaje dice que te vas pero \"disconnect.leave\" es false: "
            "pon \"leave\": true con el motivo, o no te vayas en el texto"
        )
    if leave and not claims_leaving and not mentions_farewell(reply):
        return (
            "\"disconnect.leave\" es true pero el mensaje no se despide: "
            "escribe la despedida en \"reply\""
        )
    return None
