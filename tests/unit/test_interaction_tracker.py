"""Tests del contexto de seguimiento correlacionado de interacciones."""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from airi.observability import jsonl_events as jl
from airi.observability import tracked_interaction


def _capture_logs():
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    target = logging.getLogger("test_tracker")
    target.setLevel(logging.INFO)
    target.addHandler(handler)
    target.propagate = False
    return target, handler, stream


def test_tracked_interaction_emits_full_stream():
    target, handler, stream = _capture_logs()
    try:
        catalog = ["conversation", "llm_call", "publication"]
        with tracked_interaction(
            correlation_id="cid-1", catalog=catalog, logger=jl.JsonlInteractionLogger("cid-1", catalog=catalog, logger=target)
        ) as log:
            log.module_result("conversation", "activated", duration_ms=40.0)
            # Simula una salida temprana en el codigo que no registra publicacion.
        lines = []
        for raw in stream.getvalue().splitlines():
            if raw.strip():
                lines.append(json.loads(raw))
        assert [l["interaction_id"] for l in lines] == ["cid-1"] * len(lines)
        summary = [l for l in lines if l["event"] == "interaction_summary"][0]
        assert set(summary["modules"]) == set(catalog)
        assert summary["modules"]["conversation"]["status"] == "activated"
        assert summary["total_ms"] >= 0
    finally:
        target.removeHandler(handler)


def test_tracked_interaction_emits_summary_on_exception():
    target, handler, stream = _capture_logs()
    try:
        with tracked_interaction(
            correlation_id="cid-2", logger=jl.JsonlInteractionLogger("cid-2", logger=target, catalog=["conversation"])
        ) as log:
            log.module_result("conversation", "activated", duration_ms=10.0)
            raise RuntimeError("abort")
    except RuntimeError:
        pass

    lines = []
    for raw in stream.getvalue().splitlines():
        if raw.strip():
            lines.append(json.loads(raw))
    summary = [l for l in lines if l["event"] == "interaction_summary"]
    assert summary
    assert all(l["interaction_id"] == "cid-2" for l in lines)
    target.removeHandler(handler)
