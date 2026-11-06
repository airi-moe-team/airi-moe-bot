"""Captura local opt-in de cuerpos JSON enviados al adaptador LLM."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path

from airi.ports.llm import LLMCallContext, PayloadCaptureResult

LLM_PAYLOAD_SCHEMA = "airi.llm-payload.v1"
LLM_REQUEST_SCHEMA = "airi.llm-request.v1"
LLM_RESPONSE_SCHEMA = "airi.llm-response.v1"


class LocalLlmPayloadCapture:
    """Escribe sidecars locales y valida referencias vinculadas a una traza."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    async def capture(
        self, context: LLMCallContext, payload: dict
    ) -> PayloadCaptureResult:
        try:
            return await asyncio.to_thread(self._write, context, payload)
        except Exception as exc:
            # No incluir `str(exc)`: un backend de serialización podría repetir
            # valores del objeto serializado en el mensaje de excepción.
            return PayloadCaptureResult(status="failed", error=type(exc).__name__)

    async def capture_response(
        self, context: LLMCallContext, output: dict
    ) -> PayloadCaptureResult:
        try:
            return await asyncio.to_thread(self._write, context, output, "response")
        except Exception as exc:
            return PayloadCaptureResult(status="failed", error=type(exc).__name__)

    def _write(self, context: LLMCallContext, payload: dict, kind="request") -> PayloadCaptureResult:
        if not isinstance(payload, dict):
            raise TypeError("payload debe ser un objeto JSON")
        safe_cid = _safe_component(context.correlation_id)
        safe_purpose = _safe_component(context.purpose)
        relative = Path(safe_cid) / (
            f"call-{context.call_index:04d}-{safe_purpose}-{uuid.uuid4().hex}.{kind}.json"
        )
        destination = self.base_dir / relative
        artifact = {
            "schema": (LLM_RESPONSE_SCHEMA if kind == "response" else LLM_REQUEST_SCHEMA),
            "correlation_id": context.correlation_id,
            "call_index": context.call_index,
            "purpose": context.purpose,
            "model": context.model,
            "provider": context.provider,
            ("output" if kind == "response" else "request"): payload,
        }
        raw = json.dumps(
            artifact, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            # UUID names avoid collisions; O_EXCL preserves no-overwrite semantics.
            try:
                os.link(temp_name, destination)
            except FileExistsError:
                raise
            os.unlink(temp_name)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        digest = hashlib.sha256(raw).hexdigest()
        return PayloadCaptureResult(
            status="captured", artifact_ref=relative.as_posix(), sha256=digest
        )


def _safe_component(value: str) -> str:
    value = "".join(c for c in str(value) if c.isalnum() or c in "-_ ").strip()
    return value.replace(" ", "_")[:80] or "unknown"


def load_llm_payload(
    path: str | Path,
    *,
    correlation_id: str,
    call_index: int,
    sha256: str,
) -> dict:
    """Valida checksum e identidade antes de devolver o corpo capturado."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError("no se pudo leer el artefacto de payload LLM") from exc
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("checksum del artefacto de payload LLM no coincide")
    try:
        artifact = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("artefacto de payload LLM inválido") from exc
    if not isinstance(artifact, dict) or artifact.get("schema") not in (LLM_PAYLOAD_SCHEMA, LLM_REQUEST_SCHEMA):
        raise ValueError("schema del artefacto de payload LLM no compatible")
    if artifact.get("correlation_id") != correlation_id:
        raise ValueError("correlation_id del artefacto de payload LLM no coincide")
    if artifact.get("call_index") != call_index:
        raise ValueError("call_index del artefacto de payload LLM no coincide")
    payload = artifact.get("request", artifact.get("payload"))
    if not isinstance(payload, dict):
        raise ValueError("payload del artefacto de payload LLM inválido")
    return payload


def load_llm_response(path, *, correlation_id, call_index, sha256):
    """Valida y carga la salida de aplicación capturada para replay local."""
    path = Path(path)
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError("checksum del artefacto response LLM no coincide")
        artifact = json.loads(raw)
    except OSError as exc:
        raise ValueError("no se pudo leer el artefacto response LLM") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("artefacto response LLM inválido") from exc
    if not isinstance(artifact, dict) or artifact.get("schema") != LLM_RESPONSE_SCHEMA:
        raise ValueError("schema del artefacto response LLM no compatible")
    if artifact.get("correlation_id") != correlation_id or artifact.get("call_index") != call_index:
        raise ValueError("identidad del artefacto response LLM no coincide")
    output = artifact.get("output")
    if not isinstance(output, dict) or not isinstance(output.get("content"), str):
        raise ValueError("contenido del artefacto response LLM inválido")
    return output
