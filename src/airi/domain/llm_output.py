"""Modelo de salida del LLM y parseo tolerante de su respuesta."""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import NamedTuple

from airi.domain.affinity import clamp_delta
from airi.domain.constants import (
    AFFINITY_DELTA_MAX,
    DATE_ACTION_LABEL_MAX,
    DATE_DECISIONS,
    DATE_QUESTION_OPTIONS,
    DATE_SCENE_MAX,
    LAST_CHANCE_RESULTS,
)
from airi.domain.gifs import ALLOWED_GIF_TYPES
from airi.domain.mood import MOOD_SCHEMA, normalize_mood
from airi.domain.narrative_claims import disconnect_claim_problem
from airi.domain.relationships import (
    EVIDENCE_KINDS,
    RELATIONSHIP_ACTIONS,
    ROMANTIC_STAGES,
    normalize_action,
    normalize_update,
)
from airi.domain.self_model import (
    SELF_UPDATE_OPS,
    SELF_UPDATE_SCHEMA,
    self_update_none,
)
from airi.domain.text_filters import clean_reply

log = logging.getLogger(__name__)

def extract_json_object(raw_output):
    if not isinstance(raw_output, str):
        return None
    text = raw_output.strip()
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            result, _ = decoder.raw_decode(text[match.start():])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            continue
    return None


def extract_reply_field(raw_output):
    if not isinstance(raw_output, str):
        return None
    match = re.search(r'"reply"\s*:\s*"', raw_output)
    if not match:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(raw_output[match.end() - 1:])
        if isinstance(value, str) and value.strip():
            return value.strip()
    except json.JSONDecodeError:
        pass
    return None


class ModelOutput(NamedTuple):
    """Salida normalizada del modelo (subclase de tuple: sigue siendo desempaquetable)."""

    reply: object
    gif: str
    memory: str
    diary: str
    affinity_delta: int
    date_decision: str
    date_reason: str
    last_chance_result: str
    date_question: object = None
    affinity_event: str = "none"
    # Desconexión voluntaria: {"leave": True, "reason": str} o None.
    disconnect: object = None
    # Cambio de identidad propuesto: {"key","op","value","reason","evidence"}.
    self_update: object = None
    # Cambio afectivo propuesto (StageUpdate) o None si no hay cambio.
    romantic_update: object = None
    # Propuesta/aceptación/rechazo de pareja (RelationshipAction) o None.
    relationship_action: object = None
    # Ánimo transitorio del turno: {"label","valence","energy","warmth","cause"}.
    mood: object = None


def _model_output(
    reply=None,
    gif="none",
    memory="none",
    diary="none",
    delta=0,
    decision="continue",
    reason="none",
    last_chance="none",
    question=None,
    event="none",
    disconnect=None,
    self_update=None,
    romantic_update=None,
    relationship_action=None,
    mood=None,
):
    return ModelOutput(
        reply, gif, memory, diary, delta, decision, reason, last_chance,
        question, event, disconnect, self_update,
        romantic_update, relationship_action, mood,
    )


def romantic_update_none():
    """Sentinel neutro del cambio afectivo."""
    return {
        "stage": "none",
        "evidence_kind": "none",
        "reason": "",
        "evidence_refs": [],
        "evidence_summary": "",
    }


def relationship_action_none():
    """Sentinel neutro de la acción relacional."""
    return {"action": "none", "reason": "", "evidence_refs": []}


def assistant_history_content(answer, output=None):
    """Contenido JSON para el historial de asistente.

    Guarda SIEMPRE un objeto JSON con la respuesta publicada para que el
    modelo vea su propio contrato de salida en el historial (refuerzo
    defensivo del formato). `output` es el ModelOutput del turno; si no se
    pasa, se usan los valores por defecto.
    """
    reply = answer if isinstance(answer, str) else ""
    if output is None:
        payload = {
            "reply": reply,
            "gif": "none",
            "memory": "none",
            "diary": "none",
            "affinity_delta": 0,
            "affinity_event": "none",
            "date_decision": "continue",
            "date_reason": "none",
            "last_chance_result": "none",
            "date_question": {"text": "", "options": []},
            "self_update": self_update_none(),
            "disconnect": {"leave": False, "reason": ""},
            "romantic_update": romantic_update_none(),
            "relationship_action": relationship_action_none(),
        }
    else:
        payload = {
            "reply": reply,
            "gif": getattr(output, "gif", "none") or "none",
            # memory/diary son acciones únicas, no contenido conversacional:
            # no se revocan en el historial para no repetirlas por inercia.
            "memory": "none",
            "diary": "none",
            "affinity_delta": int(getattr(output, "affinity_delta", 0) or 0),
            "affinity_event": getattr(output, "affinity_event", "none") or "none",
            "date_decision": getattr(output, "date_decision", "continue") or "continue",
            "date_reason": getattr(output, "date_reason", "none") or "none",
            "last_chance_result": (
                getattr(output, "last_chance_result", "none") or "none"
            ),
            "date_question": (
                getattr(output, "date_question", None)
                or {"text": "", "options": []}
            ),
            # Cambiar la identidad es una acción única: no se repite.
            "self_update": self_update_none(),
            # Marcharse es una acción única: en el historial se neutraliza.
            "disconnect": {"leave": False, "reason": ""},
            # Las acciones relacionales no se repiten por inercia.
            "romantic_update": romantic_update_none(),
            "relationship_action": relationship_action_none(),
        }
    return json.dumps(payload, ensure_ascii=False)


def assistant_reply_text(content):
    """Extrae el texto de respuesta de una entrada de historial de Airi.

    El historial guarda siempre un JSON con el contrato completo; esta función
    tolera también texto plano (historial antiguo o entradas sintéticas) y
    devuelve "" si no hay nada utilizable.
    """
    if not isinstance(content, str):
        return ""
    text = content.strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            return text
        if isinstance(data, dict):
            reply = data.get("reply")
            return reply if isinstance(reply, str) else ""
        return ""
    return content


def parse_date_question(raw_question):
    """Sanea la pregunta decisiva propuesta por la IA (texto no fiable).

    Devuelve `{"text": str, "options": [...]}` o `None` si no hay pregunta
    utilizable. Cada opción trae `label`, `action`, `up_chance` (0..1),
    `delta_up` y `delta_down`; los deltas se acotan al signo esperado.
    """
    if not isinstance(raw_question, dict):
        return None
    text = raw_question.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    text = " ".join(text.split())[:400]
    raw_options = raw_question.get("options")
    if not isinstance(raw_options, list):
        return None
    options = []
    for item in raw_options:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        label = item.get("label")
        if not isinstance(action, str) or not action.strip():
            continue
        if not isinstance(label, str) or not label.strip():
            label = action
        try:
            chance = float(item.get("up_chance", 0.0))
        except (TypeError, ValueError):
            chance = 0.0
        chance = max(0.0, min(1.0, chance))
        try:
            delta_up = int(item.get("delta_up", 0))
        except (TypeError, ValueError):
            delta_up = 0
        try:
            delta_down = int(item.get("delta_down", 0))
        except (TypeError, ValueError):
            delta_down = 0
        options.append(
            {
                "label": " ".join(label.split())[:DATE_ACTION_LABEL_MAX],
                "action": " ".join(action.split())[:400],
                "up_chance": chance,
                "delta_up": max(0, delta_up),
                "delta_down": min(0, delta_down),
            }
        )
        if len(options) >= DATE_QUESTION_OPTIONS:
            break
    if not options:
        return None
    return {"text": text, "options": options}


def parse_scene_list(raw_scenes):
    """Sanea las escenas iniciales propuestas por la IA."""
    if not isinstance(raw_scenes, list):
        return []
    scenes = []
    for item in raw_scenes:
        if not isinstance(item, str):
            continue
        text = " ".join(item.split())[:DATE_ACTION_LABEL_MAX]
        if text and text not in scenes:
            scenes.append(text)
        if len(scenes) >= DATE_SCENE_MAX:
            break
    return scenes


def parse_self_update(raw_update):
    """Normaliza un cambio de identidad propuesto por el modelo.

    La allowlist, los topes, el motivo obligatorio y el rate-limit se aplican
    después en `airi.domain.self_model.apply_self_update`.
    """
    if not isinstance(raw_update, dict):
        return None
    key = raw_update.get("key")
    op = raw_update.get("op")
    if not isinstance(key, str) or not isinstance(op, str):
        return None
    key = key.strip()
    op = op.strip().lower()
    if not key or key.lower() in ("none", "ninguno", "null"):
        return None
    if not op or op not in SELF_UPDATE_OPS or op == "none":
        return None
    raw_value = raw_update.get("value", "")
    if isinstance(raw_value, bool):
        value = str(raw_value)
    elif isinstance(raw_value, str):
        value = raw_value
    elif isinstance(raw_value, (int, float)):
        value = str(raw_value)
    else:
        value = ""
    reason = raw_update.get("reason", "")
    evidence = raw_update.get("evidence", "")
    reason = reason.strip() if isinstance(reason, str) else ""
    evidence = evidence.strip() if isinstance(evidence, str) else ""
    return {
        "key": key[:80],
        "op": op[:40],
        "value": value.strip()[:200],
        "reason": reason[:300],
        "evidence": evidence[:300],
    }


def parse_mood(raw_mood):
    """Normaliza el ánimo transitorio declarado por el modelo.

    Devuelve el dict canónico o `None` si no hay nada usable. El suavizado, la
    persistencia y el fallback viven en `airi.domain.mood.apply_mood`.
    """
    if isinstance(raw_mood, str) and raw_mood.strip().lower() in (
        "",
        "none",
        "ninguno",
        "null",
    ):
        return None
    return normalize_mood(raw_mood)


def parse_disconnect(raw_disconnect):
    """Normaliza la decisión de marcharse propuesta por el modelo.

    Solo se acepta si `leave` es verdadero y hay un motivo no vacío. La
    decisión contextual la toma el modelo; no hay candado por afinidad.
    """
    if not isinstance(raw_disconnect, dict):
        return None
    leave = raw_disconnect.get("leave")
    if isinstance(leave, str):
        leave = leave.strip().lower() in ("true", "1", "yes", "sí", "si")
    if not leave:
        return None
    reason = raw_disconnect.get("reason")
    reason = reason.strip()[:300] if isinstance(reason, str) else ""
    if not reason:
        return None
    return {"leave": True, "reason": reason}


def parse_model_output(
    raw_output, delta_max=None, *, allow_empty_reply=False,
    allow_raw_fallback=True,
):
    """Normaliza la salida del modelo.

    `allow_raw_fallback=False` desactiva el último recurso que publica el texto
    crudo cuando el JSON no es parseable. Se usa cuando la generación se cortó
    por longitud: en ese caso el texto crudo suele ser un JSON truncado y no
    debe llegar al usuario como si fuera la respuesta de Airi.
    """
    if not isinstance(raw_output, str) or not raw_output.strip():
        return _model_output()

    if delta_max is None:
        delta_max = AFFINITY_DELTA_MAX

    raw_output = raw_output.strip()
    parsed = extract_json_object(raw_output)
    if not isinstance(parsed, dict):
        recovered_reply = extract_reply_field(raw_output)
        if recovered_reply:
            log.warning("JSON inválido; se recuperó reply y se desactiva el GIF")
            return _model_output(reply=clean_reply(recovered_reply))
        if not allow_raw_fallback:
            log.warning(
                "JSON no recuperable y fallback de texto crudo desactivado "
                "(generación truncada); se descarta la salida."
            )
            return _model_output()
        log.warning(
            "JSON no recuperable; se conserva la respuesta original "
            "y se desactiva el GIF. Salida (primeros 500 caracteres): %r",
            raw_output[:500],
        )
        # No perder la respuesta original ni pedir al modelo que la regenere.
        recovered_reply = clean_reply(raw_output)
        if recovered_reply:
            return _model_output(reply=recovered_reply)
        return _model_output()

    reply = parsed.get("reply")
    gif_type = parsed.get("gif", "none")
    memory_action = parsed.get("memory", "none")
    diary_action = parsed.get("diary", "none")
    delta_raw = parsed.get("affinity_delta", 0)
    if not isinstance(reply, str):
        log.warning("El JSON no contiene una respuesta válida")
        return _model_output()
    if not allow_empty_reply and not reply.strip():
        log.warning("El JSON no contiene una respuesta válida")
        return _model_output()
    if not isinstance(gif_type, str):
        gif_type = "none"
    gif_type = gif_type.strip().lower()
    if gif_type not in ALLOWED_GIF_TYPES:
        log.warning("Tipo de GIF no permitido: %r", gif_type)
        gif_type = "none"
    if not isinstance(memory_action, str):
        memory_action = "none"
    memory_action = clean_reply(memory_action).strip()[:400]
    if not isinstance(diary_action, str):
        diary_action = "none"
    diary_action = clean_reply(diary_action).strip()[:400]
    # affinity_delta: entero dentro del rango permitido; el resto se ignora.
    if isinstance(delta_raw, bool) or not isinstance(delta_raw, (int, float)):
        delta = 0
    else:
        delta = int(delta_raw)
    delta = clamp_delta(delta, delta_max)
    # [CAMBIO] Candado: la afinidad solo cambia si Airi declara un motivo.
    event_raw = parsed.get("affinity_event", "none")
    if not isinstance(event_raw, str):
        affinity_event = "none"
    else:
        affinity_event = event_raw.strip()[:300]
    if affinity_event.lower() in ("", "none", "ninguno", "null"):
        if delta != 0:
            log.info("Airi devolvió delta %+d sin motivo; se ignora.", delta)
        delta = 0
    else:
        log.info("Airi decide afinidad %+d (motivo: %s)", delta, affinity_event)
    # [CAMBIO] Citas: decisión de continuidad, motivo y resultado de la última
    # oportunidad. Fuera de una cita se ignoran; aquí se normalizan.
    decision_raw = parsed.get("date_decision", "continue")
    date_decision = decision_raw.strip().lower() if isinstance(decision_raw, str) else "continue"
    if date_decision not in DATE_DECISIONS:
        date_decision = "continue"
    reason_raw = parsed.get("date_reason", "none")
    date_reason = reason_raw.strip()[:300] if isinstance(reason_raw, str) else "none"
    if not date_reason:
        date_reason = "none"
    lcr_raw = parsed.get("last_chance_result", "none")
    last_chance_result = lcr_raw.strip().lower() if isinstance(lcr_raw, str) else "none"
    if last_chance_result not in LAST_CHANCE_RESULTS:
        last_chance_result = "none"
    # [CAMBIO] Citas: la pregunta decisiva (una sola vez por cita).
    date_question = parse_date_question(parsed.get("date_question"))
    # Identidad: cambio de "yo" propuesto por Airi (opcional).
    self_update = parse_self_update(parsed.get("self_update"))
    # Ánimo transitorio del turno (opcional; si falta se usa el fallback).
    mood = parse_mood(parsed.get("mood"))
    # Marcharse: decisión contextual y excepcional de Airi.
    disconnect = parse_disconnect(parsed.get("disconnect"))
    # Relación: etapa afectiva y acción de pareja propuestas por el modelo.
    # El dominio valida después; aquí solo se normaliza la forma.
    romantic_update = normalize_update(parsed.get("romantic_update"))
    relationship_action = normalize_action(parsed.get("relationship_action"))
    claim_problem = disconnect_claim_problem(
        reply, bool(disconnect and disconnect.get("leave"))
    )
    if claim_problem:
        # No se apaga el bot si el texto y la decisión no coinciden. La capa
        # de generación puede pedir una reparación; aquí se descarta la parte
        # insegura para no fingir una marcha.
        log.warning("Salida incoherente sobre la marcha: %s", claim_problem)
        disconnect = None
    reply = clean_reply(reply)
    if not allow_empty_reply and not reply:
        log.warning("La respuesta quedó vacía después de limpiarla")
        return _model_output()
    return ModelOutput(
        reply, gif_type, memory_action, diary_action, delta,
        date_decision, date_reason, last_chance_result, date_question,
        affinity_event, disconnect, self_update, romantic_update,
        relationship_action, mood,
    )

# Esquema dedicado para turnos de sesión (espectador/activa/proactiva).
# Derivado del esquema normal sin mutarlo: añade `stay_active` y conserva
# tipos únicos (sin uniones String | Null) por compatibilidad con las
# gramáticas de generación guiada de los servidores locales.

def parse_session_output(raw_output, delta_max=None):
    """Parsea la salida de un turno de sesión.

    Devuelve `(output, stay_active, valid)`:
      - `output`: `ModelOutput` normalizado (reply puede ser "" si silencio).
      - `stay_active`: decisión del modelo (True por defecto solo si válido).
      - `valid`: False si falta `stay_active`, tipos inválidos o JSON no parseable.

    El silencio deliberado (reply == "") es válido y NO se trata como fallo.
    """
    if not isinstance(raw_output, str) or not raw_output.strip():
        return _model_output(), False, False

    parsed = extract_json_object(raw_output)
    if not isinstance(parsed, dict):
        return _model_output(), False, False

    if "stay_active" not in parsed:
        return _model_output(), False, False
    stay_active_raw = parsed.get("stay_active")
    if not isinstance(stay_active_raw, bool):
        return _model_output(), False, False

    output = parse_model_output(
        raw_output, delta_max=delta_max, allow_empty_reply=True
    )
    # parse_model_output devuelve reply=None cuando no hubo reply string.
    if not isinstance(output.reply, str) and output.reply is not None:
        return _model_output(), False, False
    if output.reply is None:
        # Sin reply string válido: fallo de contrato, no silencio.
        return _model_output(), False, False
    return output, bool(stay_active_raw), True
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "gif": {"type": "string", "enum": sorted(ALLOWED_GIF_TYPES)},
        "mood": MOOD_SCHEMA,
        "memory": {"type": "string"},
        "diary": {"type": "string"},
        "affinity_delta": {"type": "integer"},
        "affinity_event": {"type": "string"},
        "date_decision": {"type": "string", "enum": list(DATE_DECISIONS)},
        "date_reason": {"type": "string"},
        "last_chance_result": {
            "type": "string",
            "enum": list(LAST_CHANCE_RESULTS),
        },
        "date_question": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "action": {"type": "string"},
                            "up_chance": {"type": "number"},
                            "delta_up": {"type": "integer"},
                            "delta_down": {"type": "integer"},
                        },
                        "required": [
                            "label",
                            "action",
                            "up_chance",
                            "delta_up",
                            "delta_down",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["text", "options"],
            "additionalProperties": False,
        },
        "self_update": SELF_UPDATE_SCHEMA,
        "romantic_update": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": list(ROMANTIC_STAGES)},
                "evidence_kind": {
                    "type": "string",
                    "enum": ["none", *EVIDENCE_KINDS],
                },
                "reason": {"type": "string"},
                "evidence_refs": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "evidence_summary": {"type": "string"},
            },
            "required": [
                "stage",
                "evidence_kind",
                "reason",
                "evidence_refs",
                "evidence_summary",
            ],
            "additionalProperties": False,
        },
        "relationship_action": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(RELATIONSHIP_ACTIONS),
                },
                "reason": {"type": "string"},
                "evidence_refs": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["action", "reason", "evidence_refs"],
            "additionalProperties": False,
        },
        "disconnect": {
            "type": "object",
            "properties": {
                "leave": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["leave", "reason"],
            "additionalProperties": False,
        },
    },
    # Modo estricto (json_schema): TODAS las propiedades deben ir en `required`
    # y `additionalProperties: false` en cada nivel. `parse_model_output` tolera
    # claves ausentes, así que el esquema es válido también en modo clásico.
    "required": [
        "reply",
        "gif",
        "mood",
        "memory",
        "diary",
        "affinity_delta",
        "affinity_event",
        "date_decision",
        "date_reason",
        "last_chance_result",
        "date_question",
        "self_update",
        "romantic_update",
        "relationship_action",
        "disconnect",
    ],
    "additionalProperties": False,
}
# Esquema dedicado para turnos de sesión (espectador/activa/proactiva).
SESSION_RESPONSE_SCHEMA = copy.deepcopy(RESPONSE_SCHEMA)
SESSION_RESPONSE_SCHEMA["properties"]["stay_active"] = {"type": "boolean"}
SESSION_RESPONSE_SCHEMA["required"] = list(RESPONSE_SCHEMA["required"]) + ["stay_active"]
SESSION_RESPONSE_SCHEMA["properties"]["reply"] = {"type": "string"}

# Esquemas sin campos de cita, para turnos normales (sin cita activa).
_DATE_FIELDS = ("date_decision", "date_reason", "last_chance_result", "date_question")

def _strip_date_fields(schema):
    schema = copy.deepcopy(schema)
    for field in _DATE_FIELDS:
        schema["properties"].pop(field, None)
    schema["required"] = [f for f in schema["required"] if f not in _DATE_FIELDS]
    return schema

RESPONSE_SCHEMA_NO_DATE = _strip_date_fields(RESPONSE_SCHEMA)
SESSION_RESPONSE_SCHEMA_NO_DATE = _strip_date_fields(SESSION_RESPONSE_SCHEMA)


from airi.domain.capabilities import TurnCapabilities


def response_schema(capabilities: "TurnCapabilities | bool" = False, session_mode: bool = False) -> dict:
    """Devuelve el schema adecuado según las capacidades activas y el modo sesión.

    Acepta `TurnCapabilities` o un bool (compatibilidad con `in_date`).
    """
    if isinstance(capabilities, bool):
        date_active = capabilities
    else:
        date_active = getattr(capabilities, "date_active", False)
    if session_mode:
        return SESSION_RESPONSE_SCHEMA if date_active else SESSION_RESPONSE_SCHEMA_NO_DATE
    return RESPONSE_SCHEMA if date_active else RESPONSE_SCHEMA_NO_DATE
