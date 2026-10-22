"""Entry point para `python -m airi`.

Dispatch de subcomandos:
  - run: inicia el bot de Discord
  - trace: CLI de inspección de trazas
  - replay: reproduce una traza guardada
"""

import argparse

import airi.env_boot  # noqa: F401


def cmd_run(argv=None):
    """Inicia el bot de Discord."""
    # Importar aquí para evitar circularidad y mantener la importación lazy
    from airi.discord_bot.client import run_bot
    return run_bot(argv)


def cmd_trace(argv=None):
    """CLI de inspección de trazas."""
    from airi.observability.cli import main as trace_main

    return trace_main(argv)


def cmd_replay(argv=None):
    """Reproduce una traza guardada."""
    from airi.observability.replay import main as replay_main

    return replay_main(argv)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Airi — Bot de Discord con LLM local"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="inicia el bot de Discord")
    p_run.set_defaults(func=cmd_run)

    p_trace = sub.add_parser("trace", help="inspecciona trazas de turnos")
    p_trace.set_defaults(func=cmd_trace)

    p_replay = sub.add_parser("replay", help="reproduce una traza guardada")
    p_replay.set_defaults(func=cmd_replay)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
