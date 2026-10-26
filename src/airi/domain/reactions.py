"""Detección determinista de reacciones negativas y correcciones directas.

El modelo decide la afinidad, pero no debe premiar un turno en el que la
persona solo está negando, corrigiendo o quejándose. Este módulo no interpreta
opiniones normales ("no me gusta el anime"): solo interjecciones de negación y
desacuerdos dirigidos a Airi.
"""

from __future__ import annotations

import re
import unicodedata

_NEGATIVE_INTERJECTION = re.compile(
    r"^(?:no+|nop+|nel|para nada|que no)$"
)
_DIRECT_DISAGREEMENT = re.compile(
    r"\b("
    r"te (?:estas )?equivoc\w*|"
    r"estas (?:equivocad|confundid)\w*|"
    r"te confundes|"
    r"no (?:es|era|fue) (?:asi|correcto)|"
    r"no tienes razon|"
    r"estas mal"
    r")\b"
)


def _normalize(text):
    decomposed = unicodedata.normalize("NFD", text or "")
    plain = "".join(
        ch for ch in decomposed if unicodedata.category(ch) != "Mn"
    )
    return " ".join(plain.casefold().split())


def is_negative_reaction(message):
    """True si el mensaje es una negación pura o un desacuerdo directo."""
    normalized = _normalize(message).strip(" !?.,;:¡¿")
    if not normalized:
        return False
    if _NEGATIVE_INTERJECTION.fullmatch(normalized):
        return True
    return bool(_DIRECT_DISAGREEMENT.search(normalized))
