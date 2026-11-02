import asyncio
import json

import pytest

from airi.observability.replay_capture import (
    CapturedWebSearchClient,
    WebCapture,
    load_web_capture,
    normalize_query,
    write_web_capture,
)
from airi.observability.replay import _behavioral_checks
from airi.observability.trace import TurnEvent


def test_capture_round_trip_distinguishes_empty_result(tmp_path):
    path = tmp_path / "capture.json"
    path.write_text(json.dumps({
        "schema": "airi.web-capture.v1", "correlation_id": "abc",
        "status": "empty", "query": "  café  ", "results": [],
    }))
    record = load_web_capture(path, correlation_id="abc")
    client = CapturedWebSearchClient(record)

    result = asyncio.run(client.search("cafe\u0301"))

    assert result is not None and result.is_empty
    assert client.status == "captured_empty"
    assert normalize_query("  café ") == normalize_query("cafe\u0301")


def test_capture_mismatch_never_reuses_evidence(tmp_path):
    path = tmp_path / "capture.json"
    path.write_text(json.dumps({
        "schema": "airi.web-capture.v1", "correlation_id": "abc",
        "status": "results", "query": "weather today",
        "results": [{"title": "Weather", "snippet": "Sunny"}],
    }))
    client = CapturedWebSearchClient(load_web_capture(path, correlation_id="abc"))

    result = asyncio.run(client.search("weather tomorrow"))

    assert result is None
    assert client.status == "capture_mismatch"


def test_capture_writer_is_private_and_refuses_existing_artifact(tmp_path):
    path = tmp_path / "capture.json"
    write_web_capture(
        path, correlation_id="abc", status="empty", query="private query"
    )

    assert path.stat().st_mode & 0o777 == 0o600
    assert load_web_capture(path, correlation_id="abc").status == "empty"
    with pytest.raises(FileExistsError):
        write_web_capture(path, correlation_id="abc", status="empty", query="replacement")


@pytest.mark.parametrize("data", [
    {},
    {"schema": "wrong", "correlation_id": "abc", "status": "empty", "query": "x", "results": []},
    {"schema": "airi.web-capture.v1", "correlation_id": "other", "status": "empty", "query": "x", "results": []},
    {"schema": "airi.web-capture.v1", "correlation_id": "abc", "status": "empty", "query": "x", "results": [{"oops": 1}]},
])
def test_invalid_capture_rejected_without_dumping_payload(tmp_path, data):
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError):
        load_web_capture(path, correlation_id="abc")


@pytest.mark.parametrize(("capture", "requested", "client_status", "expected_result"), [
    (WebCapture("x", "not_requested", None, ()), False, "capture_missing", "not_requested"),
    (WebCapture("x", "empty", "weather today", ()), True, "captured_empty", "captured_empty"),
    (WebCapture("x", "results", "weather today", ()), True, "capture_mismatch", "capture_mismatch"),
    (WebCapture("x", "not_requested", None, ()), True, "capture_missing", "capture_missing"),
])
def test_behavior_report_keeps_decision_query_and_result_states_separate(
    capture, requested, client_status, expected_result,
):
    checks = _behavioral_checks(
        original=TurnEvent(final_reply="old"), actual_requested=requested,
        actual_query="weather tomorrow" if client_status == "capture_mismatch" else "weather today",
        capture=capture, capture_status=client_status, actual_reply="new",
        task_context=None, actual_grounded=False,
    )

    assert checks["search_result"]["status"] == expected_result
    if requested and capture.query and client_status != "capture_missing":
        assert checks["search_query"]["status"] == (
            "failed" if client_status == "capture_mismatch" else "passed"
        )
    if requested and not capture.query:
        assert checks["search_query"]["status"] == "not_evaluated"
    if not requested:
        assert checks["search_query"]["status"] == "not_evaluated"
        assert checks["grounding"]["status"] == "not_evaluated"
