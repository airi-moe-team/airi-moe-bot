"""Tests del CLI de evaluación de interacción."""

from __future__ import annotations

import json

import pytest
import tools.interaction_eval as cli


def _record(**overrides):
    payload = {
        "scenario": "pregunta_directa",
        "category": "direct_question",
        "turn": 1,
        "user": "¿café o té?",
        "reply": "Prefiero el té.",
        "parse_ok": True,
        "finish_reason": "stop",
        "disconnect": None,
        "stay_active": True,
    }
    payload.update(overrides)
    return payload


def _write(path, records):
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
        + "\n",
        encoding="utf-8",
    )
    return str(path)


def test_run_without_baseline_prints_json_and_passes(tmp_path, capsys):
    candidate = _write(tmp_path / "candidate.jsonl", [_record()])
    code = cli.main(["--run", candidate, "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["turns"] == 1


def test_run_with_baseline_reports_critical_regression(tmp_path, capsys):
    baseline = _write(tmp_path / "baseline.jsonl", [_record()])
    candidate = _write(
        tmp_path / "candidate.jsonl",
        [_record(parse_ok=False)],
    )
    code = cli.main(["--run", candidate, "--baseline", baseline, "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["regression"] is True
    assert payload["delta"]["schema_failures"] == 1


def test_quality_regression_does_not_fail_the_cli(tmp_path, capsys):
    baseline = _write(tmp_path / "baseline.jsonl", [_record()])
    candidate = _write(
        tmp_path / "candidate.jsonl",
        [_record(reply="¿Y tú?")],
    )
    code = cli.main(["--run", candidate, "--baseline", baseline, "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["quality_regression"] is True
    assert payload["regression"] is False


def test_live_writes_records_and_compares_against_baseline(
    tmp_path, capsys, monkeypatch
):
    baseline = _write(tmp_path / "baseline.jsonl", [_record()])
    out = tmp_path / "candidate.jsonl"

    async def fake_live(**kwargs):
        assert kwargs["repeat"] == 2
        assert kwargs["base_url"] == "http://example.test"
        assert kwargs["model"] == "modelo-test"
        return [_record()]

    monkeypatch.setattr(cli, "generate_live_records", fake_live)
    code = cli.main(
        [
            "--live",
            "--out",
            str(out),
            "--baseline",
            baseline,
            "--repeat",
            "2",
            "--base-url",
            "http://example.test",
            "--model",
            "modelo-test",
            "--json",
        ]
    )
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8").strip())["reply"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["regression"] is False


def test_live_requires_out(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--live"])
    assert excinfo.value.code == 2


def test_run_rejects_out(tmp_path):
    candidate = _write(tmp_path / "candidate.jsonl", [_record()])
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--run", candidate, "--out", str(tmp_path / "x.jsonl")])
    assert excinfo.value.code == 2
