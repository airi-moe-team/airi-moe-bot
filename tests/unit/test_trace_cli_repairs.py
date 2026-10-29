"""Listado CLI de reparaciones por motivo y correlation_id."""

from __future__ import annotations

import json

from airi.observability import cli


def _write_trace(root, day, cid, calls, exhausted=False):
    folder = root / day
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{cid}.json").write_text(
        json.dumps(
            {
                "correlation_id": cid,
                "kind": "message",
                "repair_exhausted": exhausted,
                "llm_calls": calls,
            }
        ),
        encoding="utf-8",
    )


def test_repairs_cli_agrupa_por_motivo_y_lista_correlation_ids(tmp_path, capsys):
    _write_trace(
        tmp_path,
        "2026-10-29",
        "abc123",
        [{"purpose": "parse_repair", "repair_reason": "truncation"}],
        exhausted=True,
    )
    _write_trace(
        tmp_path,
        "2026-10-29",
        "def456",
        [{"purpose": "quality_repair", "repair_reason": "repeat+ooc"}],
    )

    code = cli.main(["--dir", str(tmp_path), "repairs"])

    output = capsys.readouterr().out
    assert code == 0
    assert "truncation" in output and "abc123" in output
    assert "repeat+ooc" in output and "def456" in output
    assert "agotados=1" in output


def test_repairs_cli_tolera_trazas_legacy_sin_motivo(tmp_path, capsys):
    _write_trace(
        tmp_path,
        "2026-10-29",
        "old001",
        [{"purpose": "truncation_repair"}],
    )

    code = cli.main(["--dir", str(tmp_path), "repairs"])

    assert code == 0
    assert "unknown" in capsys.readouterr().out
