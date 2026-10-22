"""Máquina de estados de las citas (lógica pura)."""

from __future__ import annotations

import copy

from airi.domain.constants import (
    DATE_CRISIS_DROP,
    DATE_CRISIS_MIN_TURNS,
    DATE_END_MIN_TURNS,
    DATE_LAST_CHANCE_MAX_RECOVERY,
    DATE_MAX_SECONDS,
    DATE_MAX_TURNS,
    DATE_QUESTION_CRISIS_DROP,
    DATE_QUESTION_DELTA_MAX,
    DATE_QUESTION_MIN_TURNS,
    DATE_STATES,
    LAST_CHANCE_RESULTS,
)

# ============================================================
# CITAS: MÁQUINA DE ESTADOS (active → last_chance → final_scene → closed)
# ============================================================


def new_date_session(scene, affinity_start, now):
    """Crea una sesión de cita nueva en estado `active`.

    `affinity_start` es la afinidad al empezar la cita: sirve de techo para la
    recuperación de la última oportunidad.
    """
    try:
        start = int(affinity_start)
    except (TypeError, ValueError):
        start = 0
    return {
        "scene": str(scene or ""),
        "state": "active",
        "turns": 0,
        "affinity_start": start,
        "affinity_crisis": None,
        "crisis_reason": "none",
        "last_chance_used": False,
        "last_chance_result": "none",
        "question": None,
        "question_used": False,
        "question_pending": False,
        "question_forced": False,
        "question_invalid": False,
        "history": [],
        "started_at": float(now),
    }


def normalize_date_session(session):
    """Completa los campos que falten (p. ej. sesiones cargadas de disco)."""
    if not isinstance(session, dict):
        return None
    session.setdefault("scene", "")
    session.setdefault("state", "active")
    session.setdefault("turns", 0)
    session.setdefault("affinity_start", 0)
    session.setdefault("affinity_crisis", None)
    session.setdefault("crisis_reason", "none")
    session.setdefault("last_chance_used", False)
    session.setdefault("last_chance_result", "none")
    session.setdefault("question", None)
    session.setdefault("question_used", False)
    session.setdefault("question_pending", False)
    session.setdefault("question_forced", False)
    session.setdefault("question_invalid", False)
    session.setdefault("question_asked_at", 0.0)
    session.setdefault("history", [])
    session.setdefault("started_at", 0.0)
    if session.get("state") not in DATE_STATES:
        session["state"] = "active"
    if not isinstance(session.get("history"), list):
        session["history"] = []
    try:
        session["turns"] = int(session.get("turns", 0) or 0)
    except (TypeError, ValueError):
        session["turns"] = 0
    try:
        session["affinity_start"] = int(session.get("affinity_start", 0) or 0)
    except (TypeError, ValueError):
        session["affinity_start"] = 0
    return session


def date_turns_left(session):
    """Turnos que le quedan a la cita antes de agotar el límite."""
    if not isinstance(session, dict):
        return 0
    try:
        turns = int(session.get("turns", 0) or 0)
    except (TypeError, ValueError):
        turns = 0
    return max(0, DATE_MAX_TURNS - turns)


def date_seconds_left(session, now, max_seconds=DATE_MAX_SECONDS):
    """Segundos reales que le quedan a la cita (0 si ya expiró)."""
    if not isinstance(session, dict):
        return 0
    if session.get("state") == "closed":
        return 0
    try:
        started = float(session.get("started_at", 0.0) or 0.0)
        elapsed = float(now) - started
    except (TypeError, ValueError):
        return 0
    return max(0.0, float(max_seconds) - elapsed)


def date_expired(session, now, max_seconds=DATE_MAX_SECONDS):
    """True si la cita sigue abierta pero ha superado su duración máxima."""
    if not isinstance(session, dict):
        return False
    if session.get("state") == "closed":
        return False
    try:
        started = float(session.get("started_at", 0.0) or 0.0)
        elapsed = float(now) - started
    except (TypeError, ValueError):
        return False
    return elapsed >= float(max_seconds)


def crisis_allowed(session):
    """La crisis solo puede dispararse una vez y tras unos turnos mínimos."""
    if not isinstance(session, dict):
        return False
    if session.get("state") != "active":
        return False
    if session.get("last_chance_used"):
        return False
    try:
        turns = int(session.get("turns", 0) or 0)
    except (TypeError, ValueError):
        turns = 0
    return turns >= DATE_CRISIS_MIN_TURNS


def end_allowed(session):
    """El modelo puede cerrar la cita solo pasados unos turnos mínimos."""
    if not isinstance(session, dict):
        return False
    if session.get("state") not in ("active", "last_chance"):
        return False
    try:
        turns = int(session.get("turns", 0) or 0)
    except (TypeError, ValueError):
        turns = 0
    return turns >= DATE_END_MIN_TURNS


# ============================================================
# PREGUNTA DECISIVA (una sola por cita)
# ============================================================


def question_allowed(session):
    """Airi puede hacer la pregunta decisiva (una sola vez, pasados unos turnos)."""
    if not isinstance(session, dict):
        return False
    if session.get("state") != "active":
        return False
    if session.get("question_used") or session.get("question_pending"):
        return False
    try:
        turns = int(session.get("turns", 0) or 0)
    except (TypeError, ValueError):
        turns = 0
    return turns >= DATE_QUESTION_MIN_TURNS


def question_failed_hard(delta):
    """Un fallo en la pregunta es grave si el desplome llega al umbral."""
    try:
        value = int(delta)
    except (TypeError, ValueError):
        return False
    return value <= -DATE_QUESTION_CRISIS_DROP


def roll_question(option, rng):
    """Tira el dado de una alternativa. Devuelve `(acierto, delta)`.

    `option` es un dict con `up_chance` (0..1), `delta_up` y `delta_down`.
    El delta queda acotado a `±DATE_QUESTION_DELTA_MAX`, con signo coherente.
    """
    if not isinstance(option, dict):
        return False, 0
    try:
        chance = float(option.get("up_chance", 0.0))
    except (TypeError, ValueError):
        chance = 0.0
    chance = max(0.0, min(1.0, chance))
    win = rng.random() < chance
    raw = option.get("delta_up") if win else option.get("delta_down")
    try:
        delta = int(raw)
    except (TypeError, ValueError):
        delta = 0
    if win:
        delta = max(0, min(DATE_QUESTION_DELTA_MAX, delta))
    else:
        delta = min(0, max(-DATE_QUESTION_DELTA_MAX, delta))
    return win, delta


def question_option(session, index):
    """Devuelve la alternativa `index` de la pregunta pendiente, o None."""
    if not isinstance(session, dict):
        return None
    question = session.get("question")
    if not isinstance(question, dict):
        return None
    options = question.get("options")
    if not isinstance(options, list):
        return None
    try:
        index = int(index)
    except (TypeError, ValueError):
        return None
    if index < 0 or index >= len(options):
        return None
    option = options[index]
    return option if isinstance(option, dict) else None


def resolve_date_at_limit(session, points=0):
    """Agota los turnos: fuerza el cierre y devuelve el evento final.

    Deja siempre la sesión en estado `final_scene`.
    """
    if not isinstance(session, dict):
        return "closed"
    if session.get("state") == "last_chance":
        result = session.get("last_chance_result", "none")
        if result not in ("success", "partial"):
            session["last_chance_result"] = "fail"
            session["state"] = "final_scene"
            return "failed_last_chance"
        session["state"] = "final_scene"
        return "recovered" if result == "success" else "partial_recovery"
    session["state"] = "final_scene"
    return "ending"


def last_chance_recovery(session, result, current_points):
    """Puntos que se recuperan al salvarla en la última oportunidad.

    Nunca supera `DATE_LAST_CHANCE_MAX_RECOVERY` ni devuelve la afinidad por
    encima del valor con el que empezó la cita.
    """
    if result == "success":
        earned = DATE_LAST_CHANCE_MAX_RECOVERY
    elif result == "partial":
        earned = DATE_LAST_CHANCE_MAX_RECOVERY // 2
    else:
        earned = 0
    try:
        start = int(session.get("affinity_start", 0) or 0)
    except (TypeError, ValueError):
        start = 0
    try:
        ceiling = max(0, start - int(current_points))
    except (TypeError, ValueError):
        ceiling = 0
    return max(0, min(earned, ceiling))


def _start_question(session, payload, now):
    """Deja la sesión con una pregunta pendiente. Devuelve `("active", "question")`.

    Copia el payload (la pregunta del modelo nunca debe compartirse) y marca el
    estado para que solo pueda ocurrir una vez por cita. No existe pregunta de
    reserva: si el modelo no la propone, la cita sigue sin ella.
    """
    session["question"] = copy.deepcopy(payload)
    session["question_used"] = True
    session["question_pending"] = True
    session["question_forced"] = False
    session["question_invalid"] = False
    session["question_asked_at"] = float(now) if now is not None else 0.0
    return "active", "question"


def step_date(
    session,
    delta=0,
    points=0,
    decision="continue",
    reason="none",
    last_chance_result="none",
    end_keyword=False,
    now=None,
    question=None,
):
    """Avanza un turno la máquina de estados de la cita. Muta `session`.

    `points` es la afinidad tras aplicar el delta de este turno. Devuelve
    `(state, event)`, donde `event` describe lo ocurrido en el turno.

    La pregunta decisiva es opcional: si el modelo no la propone, la cita
    continúa y cierra por sus límites actuales sin generarla de reserva.
    """
    if not isinstance(session, dict):
        return "closed", "closed"
    normalize_date_session(session)
    state = session["state"]
    session["turns"] = int(session.get("turns", 0) or 0) + 1

    if state == "closed":
        return "closed", "closed"

    if state == "active":
        # 1) La IA propone la pregunta decisiva: se acepta si la cita lo permite.
        if (
            decision == "question"
            and question_allowed(session)
            and isinstance(question, dict)
            and question.get("options")
        ):
            return _start_question(session, question, now)
        # 2) Fallo grave en la pregunta decisiva: la cita pasa a la última
        # oportunidad aunque todavía no haya turnos para una crisis normal.
        if session.get("force_crisis"):
            session["force_crisis"] = False
            session["state"] = "last_chance"
            session["affinity_crisis"] = int(points)
            session["crisis_reason"] = str(
                reason or "la pregunta importante salió mal"
            )[:300]
            session["last_chance_used"] = True
            return "last_chance", "crisis"
        if decision == "crisis" and crisis_allowed(session):
            session["state"] = "last_chance"
            session["affinity_crisis"] = int(points)
            session["crisis_reason"] = str(reason or "none")[:300]
            session["last_chance_used"] = True
            return "last_chance", "crisis"
        drop = int(session.get("affinity_start", 0) or 0) - int(points)
        if drop >= DATE_CRISIS_DROP and crisis_allowed(session):
            session["state"] = "last_chance"
            session["affinity_crisis"] = int(points)
            session["crisis_reason"] = str(reason or "la afinidad cayó")[:300]
            session["last_chance_used"] = True
            return "last_chance", "crisis"
        # 3) Cierre de la cita (palabra clave o decisión del modelo).
        if end_keyword or (decision == "end" and end_allowed(session)):
            session["state"] = "final_scene"
            return "final_scene", "ending"
        # 4) Tope de turnos: la cita se cierra aunque la pregunta siga pendiente
        # (si nadie la responde, la cita se acaba igual).
        if session["turns"] >= DATE_MAX_TURNS:
            return "final_scene", resolve_date_at_limit(session, points)
        # 5) No hay pregunta de reserva: la cita sigue sin forzar nada.
        return "active", "continue"

    if state == "last_chance":
        result = last_chance_result if last_chance_result in LAST_CHANCE_RESULTS else "none"
        if result == "success":
            session["last_chance_result"] = "success"
            session["state"] = "final_scene"
            return "final_scene", "recovered"
        if result == "partial":
            session["last_chance_result"] = "partial"
            session["state"] = "final_scene"
            return "final_scene", "partial_recovery"
        if result == "fail":
            session["last_chance_result"] = "fail"
            session["state"] = "final_scene"
            return "final_scene", "failed_last_chance"
        if session["turns"] >= DATE_MAX_TURNS:
            return "final_scene", resolve_date_at_limit(session, points)
        return "last_chance", "continue"

    if state == "final_scene":
        session["state"] = "closed"
        return "closed", "closed"

    return "closed", "closed"
