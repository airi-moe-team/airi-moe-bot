"""CLI de trazas: `python -m airi.trace last <n>` / `show <correlation_id>`.

Lee los eventos persistidos en disco (por defecto `./traces`, configurable con
`AIRI_TRACE_DIR`). No necesita levantar el bot ni Discord.
"""

from __future__ import annotations

import argparse
import os
import sys

import airi.env_boot  # noqa: F401 — carga .env antes de usar AIRI_TRACE_DIR
from airi.observability.trace_store import load_events_from_dir


def _base_dir(cli_value=None):
    return cli_value or os.environ.get("AIRI_TRACE_DIR") or os.environ.get(
        "TRACE_DIR", "./traces"
    )


def _summary(ev):
    reply = (ev.final_reply or "").replace("\n", " ")[:80]
    errors = f" · errors={len(ev.errors)}" if ev.errors else ""
    return (
        f"{ev.correlation_id or '-':>14}  {ev.kind:<12} "
        f"user={ev.user_name or ev.user_id:<10} "
        f"delta={ev.affinity_applied:+d} "
        f"lat={ev.total_latency_ms}ms{errors}\n"
        f"                reply: {reply}"
    )


def cmd_last(args):
    events = load_events_from_dir(_base_dir(args.dir))
    if not events:
        print("No hay trazas en", _base_dir(args.dir))
        return 1
    for ev in events[-args.n:]:
        print(_summary(ev))
    return 0


def cmd_show(args):
    events = load_events_from_dir(_base_dir(args.dir))
    for ev in events:
        if ev.correlation_id == args.cid:
            print(ev.to_json())
            return 0
    print(f"No se encontró la traza {args.cid}", file=sys.stderr)
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspecciona trazas de turnos.")
    parser.add_argument("--dir", default=None,
                        help="directorio de trazas (default ./traces o AIRI_TRACE_DIR)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_last = sub.add_parser("last", help="resumen de los últimos n turnos")
    p_last.add_argument("n", type=int, nargs="?", default=5)
    p_last.set_defaults(func=cmd_last)

    p_show = sub.add_parser("show", help="JSON completo de un correlation_id")
    p_show.add_argument("cid")
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
