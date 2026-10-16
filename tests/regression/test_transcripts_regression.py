"""Regresión por transcripts: turnos grabados que no deben cambiar de resultado.

Cada fichero de `tests/fixtures/transcripts/*.jsonl` contiene una conversación
completa (un objeto JSON por línea): usuario, semilla de estado, y por turno
el texto del usuario y la respuesta CRUDA que devolvió el modelo. El runner
reinyecta esas respuestas con `FakeLLM` a través de `ConversationService`
(y `DateService` para los turnos de cita) y compara contra las expectativas
grabadas en el propio fichero.

- La primera vez que se ejecuta un transcript sin expectativas, el runner las
  GRABA (patrón auto-golden, estilo syrupy) y no falla.
- Para regenerar los goldens tras un cambio intencionado:
  `RECORD_TRANSCRIPTS=1 .venv/bin/python -m pytest tests/test_transcripts_regression.py`
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from airi.domain.affinity import affinity_level, default_entry, entry_points
from airi.domain.dates import new_date_session
from airi.domain.web import needs_web_search
from airi.services.conversation import ConversationService, TurnContext
from airi.services.date_service import DateService
from airi.testing import FakeGif, FakeLLM, FakeNotifier, FakeSearch, FakeUser, make_state

TRANSCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "transcripts")
NOW = 1_000_000.0

# Campos del turno que se congelan en el golden.
TURN_FIELDS = (
    "reply", "gif", "memory_saved", "diary_saved", "affinity_applied",
    "level_after", "leveled_up", "grounded", "skipped", "in_date",
    "date_decision", "date_event",
)


def load_transcripts():
    if not os.path.isdir(TRANSCRIPTS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(TRANSCRIPTS_DIR)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(TRANSCRIPTS_DIR, name), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append((name, json.loads(line)))
    return out


def build_state(spec):
    """Estado en memoria a partir de la semilla del transcript."""
    uid = str(spec["user"]["id"])
    seed = spec.get("seed", {})
    affinity = {uid: default_entry()}
    affinity[uid]["points"] = int(seed.get("affinity_points", 0))
    dates = {}
    for date_seed in spec.get("dates", []):
        session = new_date_session(
            date_seed.get("scene", ""),
            date_seed.get("affinity_start", 0),
            now=NOW,
        )
        # Campos extra opcionales (p. ej. question_used) para escenarios concretos.
        extra = date_seed.get("fields")
        if isinstance(extra, dict):
            session.update(extra)
        dates[str(date_seed.get("user_id", uid))] = session
    return make_state(
        affinity=affinity,
        histories={spec.get("channel_id", 0): list(seed.get("histories", []))},
        dates=dates,
    )[0]


def replay(spec):
    """Ejecuta el transcript completo y devuelve (estado, resultados_por_turno)."""
    state = build_state(spec)
    uid = spec["user"]["id"]
    user = FakeUser(uid, spec["user"]["display_name"])
    channel_id = spec.get("channel_id", 0)
    allow_web = bool(spec.get("allow_web", False))

    llm = FakeLLM()
    search = FakeSearch(result=spec.get("search_context"))
    service = ConversationService(
        llm=llm,
        state=state,
        search=search,
        gifs=FakeGif(),
        notifier=FakeNotifier(),
        clock=lambda: NOW,
        date_delta_max=8,
    )
    date_service = DateService(state=state, notifier=None, clock=lambda: NOW)

    results = []
    for turn in spec["turns"]:
        text = turn["text"]
        if allow_web and "query" in turn and needs_web_search(text):
            llm.replies.append(turn["query"])
        llm.replies.append(turn["raw_llm"])

        result = asyncio.run(service.run_turn(
            user, [(user, text)],
            TurnContext(channel_id=channel_id, allow_web=allow_web),
        ))

        date_event = None
        date_cfg = turn.get("date")
        session = state.dates.get(str(uid))
        if date_cfg and isinstance(session, dict):
            date_event = asyncio.run(date_service.process_turn(
                session,
                user=user,
                text=text,
                delta=int(date_cfg.get("delta", 0)),
                points=int(date_cfg.get("points", 0)),
                date_decision=date_cfg.get("date_decision", "continue"),
                date_reason=date_cfg.get("date_reason", "none"),
                last_chance_result=date_cfg.get("last_chance_result", "none"),
                now=NOW,
                question=date_cfg.get("question"),
            ))

        results.append((result, date_event))

    return state, results


def summarize_turn(result, date_event):
    data = {
        "reply": result.reply,
        "gif": result.gif,
        "memory_saved": result.memory_saved,
        "diary_saved": result.diary_saved,
        "affinity_applied": result.affinity_applied,
        "level_after": result.level_after,
        "leveled_up": result.leveled_up,
        "grounded": result.grounded,
        "skipped": result.skipped,
        "in_date": result.in_date,
        "date_decision": result.date_decision,
    }
    if date_event is not None:
        data["date_event"] = date_event
    return data


def summarize_final(state, spec):
    uid = str(spec["user"]["id"])
    points = entry_points(state.affinity.get(uid))
    return {
        "affinity_points": points,
        "level": affinity_level(points)[0],
        "diary_kinds": sorted({e.get("kind") for e in state.diary}),
        "memories": len(state.user_memories(uid)),
        "dates_open": sorted(state.dates.keys()),
    }


def save_golden(path, spec, expects, final):
    spec["expects"] = expects
    spec["expected_final"] = final
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(spec, ensure_ascii=False))


TRANSCRIPTS = load_transcripts()
IDS = [f"{name}:{spec['name']}" for name, spec in TRANSCRIPTS]


@pytest.mark.parametrize("name,spec", TRANSCRIPTS, ids=IDS)
def test_transcript_does_not_regress(name, spec):
    path = os.path.join(TRANSCRIPTS_DIR, name)
    state, results = replay(spec)

    expects = [summarize_turn(r, e) for r, e in results]
    final = summarize_final(state, spec)

    record = os.environ.get("RECORD_TRANSCRIPTS") == "1"
    if record or "expects" not in spec:
        save_golden(path, spec, expects, final)
        pytest.skip(
            f"golden grabado para {name}; ejecuta de nuevo para verificar "
            "(o RECORD_TRANSCRIPTS=1 para forzar)"
        )

    mismatches = []
    for i, (got, want) in enumerate(zip(expects, spec["expects"])):
        for field in TURN_FIELDS:
            if field in want and got.get(field) != want[field]:
                mismatches.append(
                    f"turno {i}: {field}: esperado {want[field]!r}, "
                    f"obtenido {got.get(field)!r}"
                )
    for key, want in spec.get("expected_final", {}).items():
        if final.get(key) != want:
            mismatches.append(
                f"final.{key}: esperado {want!r}, obtenido {final.get(key)!r}"
            )

    assert not mismatches, "\n".join([f"{name} divergió:"] + mismatches)


def test_transcripts_present():
    """Al menos un transcript debe existir para que la suite tenga regresión."""
    assert TRANSCRIPTS, f"no hay transcripts en {TRANSCRIPTS_DIR}"


def test_transcript_harness_detects_regression():
    """Un golden manipulado debe fallar la comparación (prueba del detector)."""
    name, spec = TRANSCRIPTS[0]
    tampered = dict(spec)
    tampered["expects"] = [
        dict(turn_expect, reply="MANIPULADA")
        for turn_expect in spec["expects"]
    ]
    state, results = replay(tampered)
    expects = [summarize_turn(r, e) for r, e in results]

    mismatches = []
    for i, (got, want) in enumerate(zip(expects, tampered["expects"])):
        for field in TURN_FIELDS:
            if field in want and got.get(field) != want[field]:
                mismatches.append(f"turno {i}: {field}")

    assert "turno 0: reply" in mismatches, (
        f"el runner debería detectar la divergencia en {name}"
    )
