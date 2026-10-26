"""Detección de mensajes que requieren búsqueda web.

La decisión es deliberadamente determinista: el modelo no puede pedir una
búsqueda por sí mismo. Se activa con cuatro señales:

- ``explicit``: el usuario pide buscar o verificar algo.
- ``correction``: corrige un dato concreto (con un marcador factual).
- ``question``: pregunta por un dato concreto sobre un tema ya presente.
- ``uncertainty``: Airi acaba de expresar una duda y el usuario pide confirmar.

Las correcciones, preguntas y dudas exigen un marcador factual (nombre propio o
término como "personaje", "fecha" o "precio") para no buscar ante una broma o
una opinión.
"""

from __future__ import annotations

import re
import unicodedata

from airi.domain.llm_output import assistant_reply_text

# Raíces de verbos que piden información. Se combinan con una mención web o,
# en imperativo claro, valen por sí solas.
_SEARCH_VERB = re.compile(
    r"\b(busc\w*|consulta\w*|investiga\w*|averigua\w*|comprueba\w*|verifica\w*)"
)
_WEB_MENTION = re.compile(
    r"\b(en|por|desde|mediante)\s+(internet|la web|la red|google)\b"
)
_STRONG_IMPERATIVE = re.compile(
    r"\b(busca|buscalo|buscarla|compruebalo|verificalo|consultalo|investiga|averigua)\b"
)
_FRESHNESS = re.compile(
    r"\b("
    r"noticias recientes|ultimas noticias|ultimos datos|"
    r"informacion actualizada|precio actual|cotizacion actual|"
    r"que ha pasado|estado actual de|ultima version|version actual"
    r")\b"
)

_CORRECTION = re.compile(
    r"\b("
    r"te (estas )?confund\w*|"
    r"te equivoc\w*|"
    r"estas confundid\w*|"
    r"creo que (te|estas) (confund\w*|equivoc\w*)|"
    r"no (es|era|fue|son|eran|se llama)\b|"
    r"eso (es|esta) (mal|equivocad\w*|incorrect\w*)|"
    r"no me suena"
    r")"
)
_UNCERTAINTY = re.compile(
    r"\b("
    r"creo que|no recuerdo|no me acuerdo|"
    r"no estoy(?: 100%)? segur\w*|no tengo claro|puede que|quizas|tal vez"
    r")\b"
)
_CONFIRM = re.compile(
    r"\b(sabes|cual|cuales|como se llama|quien|quienes|seguro|"
    r"me lo dices|confirmame|es correcto)\b"
)
# Pregunta factual directa ("¿sabes su nombre?") sin que Airi haya expresado
# duda todavía. Exige que el contexto tenga ya un tema identificable.
_FACTUAL_QUESTION = re.compile(
    r"\b("
    r"sabes (su|el|la|cual|quien|como)|"
    r"me dices (su|el|la|cual|quien|como)|"
    r"como se llama|como se llamaba|"
    r"quien (es|era|fue)|"
    r"cual (es|era) (el|la|su)|"
    r"(el|la) nombre"
    r")\b"
)

_FACTUAL_TERMS = re.compile(
    r"\b("
    r"nombre|nombres|fecha|fechas|ano|anos|personaje|personajes|"
    r"serie|series|anime|animes|pelicula|peliculas|obra|obras|"
    r"libro|libros|precio|precios|version|versiones"
    r")\b"
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_PROPER_NOUN = re.compile(r"\b[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]{2,}\b")
# Solo stopwords gramaticales (arranques de frase que parecen nombres
# propios por la mayúscula). El nombre del bot y el del interlocutor se
# excluyen dinámicamente con ``exclude_names`` para no acoplar la lista a
# usuarios ni temas concretos.
_PROPER_NOUN_STOPWORDS = {
    "uhm", "ehh", "oh", "dios", "bueno", "pero",
    "aunque", "creo", "sabes", "mira", "oye", "hola", "vale", "entonces",
    "que", "como", "cuando", "donde", "porque", "esto", "esta", "este",
    "eso", "esa", "ese", "todo", "nada", "algo", "muy", "mas", "menos",
    "solo", "tambien", "siempre", "nunca", "ahora", "luego", "despues",
    "primero", "ultimo", "ultima", "siguiente",
    "los", "las", "un", "una", "unos", "unas", "del", "al", "se", "su",
    "sus", "mi", "mis", "tu", "tus", "hay", "fue", "era", "son", "es",
    "ser", "estar", "estoy", "tiene", "tengo", "sino", "mientras",
    "desde", "hasta", "para", "por", "con", "sin", "sobre", "entre",
}

_TYPO_FIXES = (
    ("inernet", "internet"),
    ("intenet", "internet"),
    ("internert", "internet"),
    ("interent", "internet"),
)

_CONTEXT_HISTORY_LIMIT = 4


def _normalize(text):
    """Minúsculas, sin tildes, espacios colapsados y typos frecuentes."""
    decomposed = unicodedata.normalize("NFD", text or "")
    plain = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    plain = " ".join(plain.casefold().split())
    for wrong, right in _TYPO_FIXES:
        plain = plain.replace(wrong, right)
    return plain


def _context_texts(history, snapshot, *, limit=_CONTEXT_HISTORY_LIMIT):
    """Textos recientes (y snapshot pasivo) para buscar marcadores factuales."""
    texts = []
    for msg in reversed(history or ()):
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if msg.get("role") == "assistant":
            content = assistant_reply_text(content)
        if content:
            texts.append(str(content))
        if len(texts) >= limit:
            break
    for entry in snapshot or ():
        if isinstance(entry, dict):
            content = entry.get("content")
        else:
            content = getattr(entry, "content", "")
        if content:
            texts.append(str(content))
    return texts


def _last_assistant_reply(history):
    for msg in reversed(history or ()):
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            return assistant_reply_text(msg.get("content"))
    return ""


def _normalized_names(names):
    return {
        _normalize(name)
        for name in names or ()
        if isinstance(name, str) and name.strip()
    }


def _has_factual_marker(text, context=(), *, exclude_names=frozenset()):
    if _FACTUAL_TERMS.search(_normalize(text)) or _YEAR.search(str(text or "")):
        return True
    for candidate in (text, *context):
        if not isinstance(candidate, str):
            continue
        for match in _PROPER_NOUN.finditer(candidate):
            name = _normalize(match.group(0))
            if name in _PROPER_NOUN_STOPWORDS or name in exclude_names:
                continue
            return True
    return False


def _is_explicit(normalized):
    if not normalized:
        return False
    if _STRONG_IMPERATIVE.search(normalized) or _FRESHNESS.search(normalized):
        return True
    if _WEB_MENTION.search(normalized) and _SEARCH_VERB.search(normalized):
        return True
    return False


def detect_search_intent(
    message, *, history=(), snapshot=(), exclude_names=()
):
    """Devuelve ``explicit``, ``correction``, ``question``, ``uncertainty``
    o ``None``.

    ``history`` es el historial previo al mensaje actual y ``snapshot`` la
    captura pasiva del modo espectador. ``exclude_names`` son los nombres que
    no deben contar como tema factual (el bot y el interlocutor actual), para
    que la detección no dependa de usuarios concretos. No se consulta al LLM:
    la intención se decide con reglas para no añadir una llamada extra antes de
    saber si hace falta buscar.
    """
    normalized = _normalize(message)
    if _is_explicit(normalized):
        return "explicit"

    context = _context_texts(history, snapshot)
    excluded = _normalized_names(exclude_names)

    if _CORRECTION.search(normalized) and _has_factual_marker(
        message, context, exclude_names=excluded
    ):
        return "correction"

    reply = _last_assistant_reply(history)
    if (
        reply
        and _UNCERTAINTY.search(_normalize(reply))
        and _CONFIRM.search(normalized)
        and _has_factual_marker(reply, context, exclude_names=excluded)
    ):
        return "uncertainty"

    if _FACTUAL_QUESTION.search(normalized) and _has_factual_marker(
        "", context, exclude_names=excluded
    ):
        return "question"

    return None


def needs_web_search(message, *, history=(), snapshot=(), exclude_names=()):
    """Compatibilidad booleana de :func:`detect_search_intent`."""
    return (
        detect_search_intent(
            message,
            history=history,
            snapshot=snapshot,
            exclude_names=exclude_names,
        )
        is not None
    )


def recent_topic_terms(texts, *, exclude_names=(), limit=8):
    """Entidades con mayúscula recientes, de la más nueva a la más vieja.

    Se usa solo para anclar la consulta web (un nombre de serie, personaje,
    lugar...), nunca como hecho verificado. ``exclude_names`` elimina el bot y
    el interlocutor actual para no convertir nombres de personas en temas.
    """
    if limit <= 0:
        return []
    excluded = _normalized_names(exclude_names)
    seen = {}
    for index, text in enumerate(texts or ()):
        if not isinstance(text, str):
            continue
        for match in _PROPER_NOUN.finditer(text):
            raw = match.group(0)
            normalized = _normalize(raw)
            if len(normalized) < 3:
                continue
            if (
                normalized in _PROPER_NOUN_STOPWORDS
                or normalized in excluded
            ):
                continue
            seen[normalized] = (index, raw)
    ordered = sorted(seen.values(), key=lambda item: item[0], reverse=True)
    return [raw for _index, raw in ordered[:limit]]


def web_results_relevant(
    web_context, query, topic_terms=(), *, exclude_names=()
):
    """True si los resultados cubren el tema de la query (o el tema ancla).

    Si la query contiene entidades propias, se exige que al menos una aparezca
    en los resultados. Así una query correcta no se invalida por entidades
    viejas del historial. Si la query no contiene entidades (p. ej. "búscalo"),
    se usa el ancla de la conversación. Sin entidades no se puede juzgar y se
    deja pasar.
    """
    if not web_context:
        return True
    query_terms = recent_topic_terms(
        [query], exclude_names=exclude_names, limit=12
    )
    candidates = query_terms or [
        term for term in topic_terms or () if isinstance(term, str)
    ][:12]
    if not candidates:
        return True
    haystack = _normalize(str(web_context))
    return any(_normalize(term) in haystack for term in candidates)

