"""Reproduce un turno guardado: `python -m airi.replay <trace.json>`.

Reinyecta el turno contra un servicio montado con dobles (FakeLLM con el
`raw_llm` guardado, estado en memoria reconstruido desde la traza) y verifica
que el resultado coincide con lo registrado. Sale con código 0 si la
reproducción coincide y 1 si diverge o la traza no es reproducible.

Uso típico para depurar un bug en producción:

    TRACE_DIR=./traces python bot.py        # el bot guarda ./traces/<día>/<cid>.json
    python -m airi.replay ./traces/2026-10-14/ab12cd34ef56.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass

import aiohttp

import airi.env_boot  # noqa: F401
from airi.adapters.http_llm import build_llm
from airi.domain.affinity import default_entry
from airi.domain.time_perception import TimeConfig
from airi.observability.trace import TurnEvent, load_turn_trace
from airi.ports.llm import LLMMeta
from airi.services.conversation import ConversationService, TurnContext
from airi.services.date_service import DateService
from airi.services.state import AppState

SESSION_KINDS = {"spectator", "active", "proactive"}


def _time_config_from_event(ev: TurnEvent) -> TimeConfig | None:
    """Reusa la configuración capturada; trazas antiguas usan Settings actuales."""
    data = ev.time_context if isinstance(ev.time_context, dict) else {}
    if "enabled" not in data:
        return None
    return TimeConfig(
        enabled=bool(data.get("enabled")),
        timezone=str(data.get("timezone") or ""),
    )


class ReplayLLM:
    """LLM que devuelve la respuesta cruda guardada en el evento."""

    def __init__(self, raw_llm, meta=None):
        self.raw_llm = raw_llm or ""
        self.meta = meta or {}
        self.calls = []

    async def chat(self, messages, **kwargs):
        content, _meta = await self.chat_with_meta(messages, **kwargs)
        return content

    async def chat_with_meta(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        meta = LLMMeta(
            finish_reason=self.meta.get("finish_reason"),
            usage=self.meta.get("usage") or {},
        )
        return self.raw_llm, meta


class FakeUser:
    """Sustituto mínimo de usuario para el replay."""

    def __init__(self, user_id, display_name):
        self.id = user_id
        self.display_name = display_name


@dataclass
class ReplayResult:
    """Resultado de reproducir un evento, con la comparación contra el original."""

    final_reply: str | None = None
    affinity_delta_applied: int | None = None
    date_event: str | None = None
    gif_sent: bool | None = None
    memory_saved: str | None = None
    diary_saved: str | None = None
    conversation_mode: str | None = None
    stay_active: bool | None = None
    matches_original: bool = False
    reproducible: bool = True
    checks: dict | None = None

    def to_dict(self):
        return asdict(self)


def _coerce_uid(user_id):
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return user_id


def build_state_from_event(ev: TurnEvent) -> tuple[AppState, object]:
    """Reconstruye el estado en memoria justo antes del turno.

    Usa los `state_snapshot_*` si están (eventos nuevos); si no, cae al
    comportamiento aproximado de las trazas antiguas. El decay se desactiva
    fijando `last_interaction` al inicio del turno.
    """
    uid = _coerce_uid(ev.user_id)
    affinity = {}
    if ev.state_snapshot_affinity:
        affinity[str(uid)] = dict(ev.state_snapshot_affinity)
    else:
        entry = default_entry()
        entry["points"] = ev.affinity_before
        affinity[str(uid)] = entry
    if isinstance(affinity.get(str(uid)), dict):
        affinity[str(uid)]["last_interaction"] = 0.0
    dates = {}
    if ev.state_snapshot_date:
        dates[str(uid)] = dict(ev.state_snapshot_date)
    state = AppState(
        affinity=affinity,
        world=dict(ev.state_snapshot_world) if ev.state_snapshot_world else {},
        dates=dates,
        memories={str(uid): [dict(m) for m in ev.state_snapshot_memories]}
        if ev.state_snapshot_memories else {},
        diary=[dict(e) for e in ev.state_snapshot_diary],
        users={str(uid): {"name": ev.user_name or str(uid)}},
        histories={0: []},
    )
    return state, uid


def _mount_event(ev: TurnEvent):
    """Prepara estado, usuario y mensajes de un evento (sin LLM ni servicio)."""
    state, uid = build_state_from_event(ev)
    user = FakeUser(uid, ev.user_name or str(uid))
    before = list(ev.history_in)
    n_in = len(ev.messages_in)
    base_history = before[:len(before) - n_in] if n_in and len(before) >= n_in else []
    if ev.in_date and str(uid) in state.dates:
        state.dates[str(uid)]["history"] = list(base_history)
    else:
        state.histories[0] = base_history
    messages = [(user, m.get("text", "")) for m in ev.messages_in]
    return state, uid, user, messages


async def _run_event(ev: TurnEvent) -> ReplayResult:
    """Núcleo del replay a partir de un evento ya cargado."""
    if ev.raw_llm is None:
        return ReplayResult(
            reproducible=False,
            matches_original=False,
            checks={"raw_llm": "ausente (traza guardada sin respuesta cruda)"},
        )
    state, uid, user, messages = _mount_event(ev)
    llm = ReplayLLM(ev.raw_llm, meta={
        "finish_reason": ev.llm_finish_reason,
        "usage": ev.llm_usage,
    })
    svc = ConversationService(
        llm=llm, state=state, search=None, gifs=None, notifier=None,
        clock=lambda: ev.started_at or 0.0, traces=None,
        time_config=_time_config_from_event(ev),
    )
    result = await svc.run_turn(
        user, messages,
        TurnContext(
            channel_id=0,
            allow_web=False,
            correlation_id=ev.correlation_id,
            conversation_mode=(ev.kind if ev.kind in SESSION_KINDS else "normal"),
            conversation_reason=ev.spectator_reason or "",
        ),
    )
    # La cita avanza fuera de `run_turn`; reproducimos ese paso con la sesión
    # reconstruida desde el snapshot para comparar `date_event`.
    date_event = None
    session = state.dates.get(str(uid))
    if ev.in_date and isinstance(session, dict):
        date_svc = DateService(
            state=state, notifier=None, clock=lambda: ev.started_at or 0.0
        )
        date_event = await date_svc.process_turn(
            session,
            user=user,
            text="\n".join(m.get("text", "") for m in ev.messages_in),
            delta=result.affinity_delta,
            points=state.entry_points(uid),
            date_decision=result.date_decision,
            date_reason=result.date_reason,
            last_chance_result=result.last_chance_result,
            now=ev.started_at or 0.0,
        )
    checks = {
        "reply": (result.reply or "") == (ev.final_reply or ""),
        "skipped": result.skipped == ev.skipped,
        "gif_requested": result.gif == ev.gif,
        "affinity_applied": result.affinity_applied == ev.affinity_applied,
        "grounded": result.grounded == ev.grounded,
        "memory_saved": (result.memory_action if result.memory_saved else None)
        == ev.memory_saved,
        "session_schema": (
            ("stay_active" in (llm.calls[0]["kwargs"].get("schema") or {}).get("properties", {}))
            == (ev.kind in SESSION_KINDS)
        ) if llm.calls else False,
    }
    if ev.stay_active is not None:
        checks["stay_active"] = result.stay_active == ev.stay_active
    # Solo se compara si la traza capturó `date_event` (trazas antiguas no lo
    # tienen; entonces el paso de cita no es verificable).
    if ev.date_event is not None:
        checks["date_event"] = date_event == ev.date_event
    return ReplayResult(
        final_reply=result.reply,
        affinity_delta_applied=result.affinity_applied,
        date_event=date_event if date_event is not None else ev.date_event,
        gif_sent=ev.gif_sent,
        memory_saved=ev.memory_saved,
        diary_saved=ev.diary_saved,
        conversation_mode=(ev.kind if ev.kind in SESSION_KINDS else "normal"),
        stay_active=result.stay_active,
        matches_original=all(checks.values()),
        reproducible=True,
        checks=checks,
    )


async def replay_trace(trace_path) -> ReplayResult:
    """Reproduce el turno de un evento en disco. No lanza excepciones."""
    ev = load_turn_trace(trace_path)
    return await _run_event(ev)


async def run_live_trace(trace_path, *, repeat=1):
    """Reconstruye el turno de la traza y lo re-infiere con el LLM real.

    A diferencia de `replay_trace`, aquí SÍ se consulta el backend configurado
    (`LLM_BASE_URL`, por defecto llama-server local). El estado es efímero y
    `notifier`/`gifs`/`search` son None: no se publica en Discord ni se
    persiste nada fuera de memoria.
    """
    ev = load_turn_trace(trace_path)
    results = []
    async with aiohttp.ClientSession() as session:
        for i in range(max(1, repeat)):
            state, uid, user, messages = _mount_event(ev)
            llm = build_llm(session)
            svc = ConversationService(
                llm=llm, state=state, search=None, gifs=None, notifier=None,
                clock=lambda: ev.started_at or 0.0, traces=None,
                time_config=_time_config_from_event(ev),
            )
            result = await svc.run_turn(
                user, messages,
                TurnContext(
                    channel_id=0, allow_web=False,
                    correlation_id=f"{ev.correlation_id}-live{i + 1}",
                    conversation_mode=(ev.kind if ev.kind in SESSION_KINDS else "normal"),
                    conversation_reason=ev.spectator_reason or "",
                ),
            )
            results.append(result)
    return results


def check_trace(trace):
    """Compatibilidad: envuelve el replay devolviendo (ok, informe)."""
    result = asyncio.run(_run_event(trace))
    report = {
        "correlation_id": trace.correlation_id,
        "reproducible": result.reproducible,
        "checks": result.checks or {},
        "expected": {"reply": trace.final_reply,
                     "affinity_applied": trace.affinity_applied},
        "got": {"reply": result.final_reply,
                "affinity_applied": result.affinity_delta_applied},
    }
    return result.matches_original, report


def emit_test(trace_path, output_path=None) -> str:
    """Genera un test pytest que verifica el replay del evento.

    Escribe `tests/integration/test_regression_<cid>.py` (o `output_path`) y
    devuelve su contenido.
    """
    ev = load_turn_trace(trace_path)
    cid = ev.correlation_id or "unknown"
    if output_path is None:
        output_path = os.path.join(
            "tests", "integration", f"test_regression_{cid}.py"
        )
    content = (
        '"""Test de regresión generado desde la traza '
        f'{cid} (`python -m airi.replay --emit-test`)."""\n\n'
        "import asyncio\n"
        "import os\n\n"
        "from airi.observability.replay import replay_trace\n\n"
        "TRACE = os.path.join(os.path.dirname(__file__), '..', 'fixtures', "
        f"'traces', '{cid}.json')\n\n\n"
        f"def test_regression_{cid}():\n"
        "    result = asyncio.run(replay_trace(TRACE))\n"
        "    assert result.reproducible, 'la traza no tiene raw_llm'\n"
        "    assert result.matches_original, f'divergencia: {result.checks}'\n"
    )
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return content


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reproduce un turno desde su traza.")
    parser.add_argument("trace", help="Ruta al fichero <cid>.json")
    parser.add_argument("--emit-test", action="store_true",
                        help="genera un test de regresión en vez de reproducir")
    parser.add_argument("--out", default=None, help="ruta de salida para --emit-test")
    parser.add_argument("--live", action="store_true",
                        help="re-infiere el turno contra el LLM real (LLM_BASE_URL) "
                             "en vez de reutilizar la respuesta guardada")
    parser.add_argument("--repeat", type=int, default=1,
                        help="número de inferencias con --live (default 1)")
    args = parser.parse_args(argv)

    try:
        load_turn_trace(args.trace)
    except Exception as exc:
        print(f"ERROR: no se pudo leer la traza: {exc}", file=sys.stderr)
        return 2

    if args.emit_test:
        emit_test(args.trace, args.out)
        print(f"Test de regresión generado: {args.out or 'tests/integration/test_regression_<cid>.py'}")
        return 0

    if args.live:
        try:
            results = asyncio.run(run_live_trace(args.trace, repeat=args.repeat))
        except Exception as exc:
            print(f"ERROR: la inferencia live falló: {exc}", file=sys.stderr)
            return 2
        for i, result in enumerate(results, start=1):
            print(json.dumps({
                "sample": i,
                "reply": result.reply,
                "gif": result.gif,
                "skipped": result.skipped,
            }, ensure_ascii=False, indent=2))
        return 0

    result = asyncio.run(replay_trace(args.trace))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if not result.reproducible:
        return 1
    return 0 if result.matches_original else 1


if __name__ == "__main__":
    raise SystemExit(main())
