"""Modelo de salida del LLM y parseo tolerante de su respuesta."""

from __future__ import annotations

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
):
    return ModelOutput(
        reply, gif, memory, diary, delta, decision, reason, last_chance,
        question, event,
    )


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
        }
    return json.dumps(payload, ensure_ascii=False)


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


def parse_model_output(raw_output, delta_max=None):
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
    if not isinstance(reply, str) or not reply.strip():
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
    memory_action = memory_action.strip()[:400]
    if not isinstance(diary_action, str):
        diary_action = "none"
    diary_action = diary_action.strip()[:400]
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
    reply = clean_reply(reply)
    if not reply:
        log.warning("La respuesta quedó vacía después de limpiarla")
        return _model_output()
    return ModelOutput(
        reply, gif_type, memory_action, diary_action, delta,
        date_decision, date_reason, last_chance_result, date_question,
        affinity_event,
    )

# Esquema JSON que la respuesta del modelo debe cumplir.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "gif": {"type": "string", "enum": sorted(ALLOWED_GIF_TYPES)},
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
    },
    # Modo estricto (json_schema): TODAS las propiedades deben ir en `required`
    # y `additionalProperties: false` en cada nivel. `parse_model_output` tolera
    # claves ausentes, así que el esquema es válido también en modo clásico.
    "required": [
        "reply",
        "gif",
        "memory",
        "diary",
        "affinity_delta",
        "affinity_event",
        "date_decision",
        "date_reason",
        "last_chance_result",
        "date_question",
    ],
    "additionalProperties": False,
}
