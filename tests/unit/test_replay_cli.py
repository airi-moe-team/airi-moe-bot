import json

import pytest

from airi.observability.replay import load_task_context, main


def test_web_live_requires_live_before_reading_trace():
    with pytest.raises(SystemExit) as error:
        main(["nonexistent.json", "--web-live"])
    assert error.value.code == 2


@pytest.mark.parametrize("arguments", [
    ["nonexistent.json", "--behavioral", "--live", "--capture", "capture.json"],
    ["nonexistent.json", "--capture", "capture.json"],
    ["nonexistent.json", "--task-context", "task.json"],
    ["nonexistent.json", "--repeat", "2"],
    ["nonexistent.json", "--live", "--repeat", "0"],
    ["nonexistent.json", "--live", "--emit-test"],
])
def test_incompatible_replay_flags_rejected_before_reading_trace(arguments):
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2


def test_replay_help_documents_explicit_web_permission(capsys):
    with pytest.raises(SystemExit) as error:
        main(["--help"])

    output = capsys.readouterr().out
    assert error.value.code == 0
    assert "--behavioral" in output
    assert "--web-live" in output
    assert "requiere --live" in output


def test_task_context_fixture_is_normalized_and_bounded(tmp_path):
    fixture = tmp_path / "task.json"
    fixture.write_text(json.dumps({
        "goal": "  terminar   el informe ",
        "constraints": ["no enviar"],
        "progress": "borrador listo",
        "next_step": "revisar",
    }))

    context = load_task_context(fixture)

    assert context == {
        "goal": "terminar el informe", "constraints": ["no enviar"],
        "progress": "borrador listo", "next_step": "revisar",
    }


def test_task_context_fixture_error_does_not_echo_private_content(tmp_path):
    fixture = tmp_path / "task.json"
    secret = "contenido privado" * 100
    fixture.write_text(json.dumps({"progress": secret}))

    with pytest.raises(ValueError) as error:
        load_task_context(fixture)

    assert secret not in str(error.value)
