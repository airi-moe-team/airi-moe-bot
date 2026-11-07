import asyncio
import hashlib
import json
import stat
from pathlib import Path

import pytest

from airi.observability.llm_payload_capture import (
    LocalLlmPayloadCapture,
    load_llm_payload,
)
from airi.ports.llm import LLMCallContext


def test_local_capture_round_trips_complete_payload_and_hash(tmp_path):
    payload = {
        "model": "local-model",
        "messages": [{"role": "system", "content": "private prompt"}],
        "temperature": 0.3,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    context = LLMCallContext("trace-123", "primary", 1)
    capture = LocalLlmPayloadCapture(tmp_path)

    result = asyncio.run(capture.capture(context, payload))

    assert result.status == "captured"
    assert result.artifact_ref.startswith("trace-123/")
    path = tmp_path / result.artifact_ref
    raw = path.read_bytes()
    artifact = json.loads(raw)
    assert artifact["schema"] == "airi.llm-request.v1"
    assert artifact["correlation_id"] == "trace-123"
    assert artifact["purpose"] == "primary"
    assert artifact["call_index"] == 1
    assert artifact["request"] == payload
    assert result.sha256 == hashlib.sha256(raw).hexdigest()


def test_response_capture_preserves_full_content_and_loader_checks_identity(tmp_path):
    from airi.observability.llm_payload_capture import (
        LLM_RESPONSE_SCHEMA,
        load_llm_response,
    )
    context = LLMCallContext("cid", "primary", 2)
    output = {"content": "respuesta completa" * 1000,
              "tool_calls": [{"name": "search", "arguments": {"q": "x"}}]}
    capture = LocalLlmPayloadCapture(tmp_path)

    result = asyncio.run(capture.capture_response(context, output))
    loaded = load_llm_response(
        tmp_path / result.artifact_ref, correlation_id="cid", call_index=2,
        sha256=result.sha256,
    )

    assert result.status == "captured"
    assert loaded == output
    assert json.loads((tmp_path / result.artifact_ref).read_text())["schema"] == LLM_RESPONSE_SCHEMA


def test_capture_uses_unique_names_and_loader_validates_hash(tmp_path):
    payload = {"model": "m", "messages": []}
    capture = LocalLlmPayloadCapture(tmp_path)

    first = asyncio.run(capture.capture(LLMCallContext("cid", "primary", 1), payload))
    second = asyncio.run(capture.capture(LLMCallContext("cid", "primary", 1), payload))

    assert first.artifact_ref != second.artifact_ref
    loaded = load_llm_payload(
        tmp_path / first.artifact_ref,
        correlation_id="cid",
        call_index=1,
        sha256=first.sha256,
    )
    assert loaded == payload


def test_loader_rejects_checksum_mismatch_without_dumping_payload(tmp_path):
    capture = LocalLlmPayloadCapture(tmp_path)
    result = asyncio.run(
        capture.capture(LLMCallContext("cid", "primary", 1), {"messages": ["secret"]})
    )

    with pytest.raises(ValueError, match="checksum") as error:
        load_llm_payload(
            tmp_path / result.artifact_ref,
            correlation_id="cid",
            call_index=1,
            sha256="0" * 64,
        )

    assert "secret" not in str(error.value)


def test_loader_rejects_wrong_correlation_id(tmp_path):
    capture = LocalLlmPayloadCapture(tmp_path)
    result = asyncio.run(
        capture.capture(LLMCallContext("cid", "review", 2), {"model": "m"})
    )

    with pytest.raises(ValueError, match="correlation_id"):
        load_llm_payload(
            tmp_path / result.artifact_ref,
            correlation_id="other",
            call_index=2,
            sha256=result.sha256,
        )


def test_loader_rejects_wrong_call_index(tmp_path):
    capture = LocalLlmPayloadCapture(tmp_path)
    result = asyncio.run(
        capture.capture(LLMCallContext("cid", "review", 2), {"model": "m"})
    )

    with pytest.raises(ValueError, match="call_index"):
        load_llm_payload(
            tmp_path / result.artifact_ref,
            correlation_id="cid",
            call_index=1,
            sha256=result.sha256,
        )


def test_loader_rejects_missing_and_malformed_sidecars(tmp_path):
    with pytest.raises(ValueError, match="no se pudo leer"):
        load_llm_payload(
            tmp_path / "missing.json",
            correlation_id="cid",
            call_index=1,
            sha256="0" * 64,
        )

    malformed = tmp_path / "malformed.json"
    malformed.write_text("not-json", encoding="utf-8")
    digest = hashlib.sha256(malformed.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="inválido"):
        load_llm_payload(
            malformed,
            correlation_id="cid",
            call_index=1,
            sha256=digest,
        )


def test_capture_failure_state_is_structured_and_never_contains_payload():
    class BrokenCapture(LocalLlmPayloadCapture):
        def _write(self, context, payload):
            raise OSError("disk full")

    result = asyncio.run(
        BrokenCapture(Path("unused")).capture(
            LLMCallContext("cid", "primary", 1), {"messages": ["secret"]}
        )
    )

    assert result.status == "failed"
    assert result.artifact_ref is None
    assert "secret" not in (result.error or "")


def test_capture_creates_private_directories_and_files(tmp_path):
    base = tmp_path / "private" / "artifacts"
    capture = LocalLlmPayloadCapture(base)

    result = asyncio.run(
        capture.capture_response(LLMCallContext("cid", "peer_primary", 1), {"content": "x"})
    )

    assert result.status == "captured"
    assert stat.S_IMODE(base.stat().st_mode) == 0o700
    assert stat.S_IMODE((base / "cid").stat().st_mode) == 0o700
    assert stat.S_IMODE((base / result.artifact_ref).stat().st_mode) == 0o600


def test_capture_does_not_change_permissions_of_existing_directories(tmp_path):
    base = tmp_path / "existing"
    base.mkdir(mode=0o755)
    base.chmod(0o755)
    capture = LocalLlmPayloadCapture(base)

    asyncio.run(
        capture.capture(LLMCallContext("cid", "peer_primary", 1), {"model": "m"})
    )

    assert stat.S_IMODE(base.stat().st_mode) == 0o755
    assert stat.S_IMODE((base / "cid").stat().st_mode) == 0o700
