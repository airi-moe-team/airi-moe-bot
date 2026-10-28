"""Cliente LLM sobre APIs compatibles con Chat Completions (llama.cpp, OpenAI...).

Un único adaptador HTTP para todos los proveedores: `llama-server` de llama.cpp,
la API de OpenAI y cualquier compatible (OpenRouter, Groq, vLLM, LM Studio...).
Las diferencias de compatibilidad viven en el *perfil* (`LLM_PROVIDER`), no en
clases distintas: la fábrica `build_llm()` concentra la configuración del
entorno y los servicios siguen usando el `Protocol` `airi.ports.llm.LLMClient`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass

import aiohttp

from airi.domain.constants import env_flag, env_int
from airi.ports.llm import LLMMeta

log = logging.getLogger(__name__)

DEFAULT_MAX_OUTPUT_TOKENS = 8000
#: URL por defecto para el backend local.
DEFAULT_BASE_URL = "http://127.0.0.1:7000"
#: Modelo por defecto (GGUF local); en perfiles remotos debe configurarse.
DEFAULT_MODEL = "Qwen3.6-35B-A3B-MTP-UD-IQ3_S"
#: Perfiles de compatibilidad soportados.
LLM_PROVIDERS = ("llama", "openai", "openai-compatible")
#: Modos de razonamiento de `LLM_THINKING_MODE`:
#: - `auto`: se desactiva solo en los turnos rápidos (comportamiento histórico).
#: - `on`: razonamiento siempre activo (ignora los pedidos de desactivarlo).
#: - `off`: razonamiento siempre desactivado.
LLM_THINKING_MODES = ("auto", "on", "off")

_ERROR_DETAIL_LIMIT = 300


async def _iter_sse_data(content):
    """Yield `data:` event payloads across arbitrary network chunk boundaries."""
    buffer = b""
    data_lines = []

    def consume_line(raw_line):
        line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
        if not line:
            return "event" if data_lines else None
        if line.startswith(":"):
            return None
        if line.startswith("data:"):
            value = line[5:]
            data_lines.append(value[1:] if value.startswith(" ") else value)
        return None

    async for chunk in content.iter_any():
        if not isinstance(chunk, (bytes, bytearray)):
            chunk = str(chunk).encode("utf-8")
        buffer += bytes(chunk)
        while b"\n" in buffer:
            raw_line, buffer = buffer.split(b"\n", 1)
            if consume_line(raw_line):
                yield "\n".join(data_lines)
                data_lines.clear()
    if buffer:
        consume_line(buffer)
    if data_lines:
        yield "\n".join(data_lines)


def _numeric_timings(value):
    if not isinstance(value, dict):
        return None
    timings = {
        str(key): item
        for key, item in value.items()
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    }
    return timings or None


def _reasoning_token_count(usage):
    if not isinstance(usage, dict):
        return None
    details = usage.get("completion_tokens_details")
    value = details.get("reasoning_tokens") if isinstance(details, dict) else None
    if value is None:
        value = usage.get("reasoning_tokens")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _env_str(*names, default=""):
    """Primer valor de entorno no vacío entre `names` (o `default`)."""
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _env_flag(name, default):
    """Booleano desde el env (`1/0`, `true/false`...); inválido → `default`."""
    return env_flag(name, default)


def resolve_provider(raw):
    """Normaliza `LLM_PROVIDER`; cualquier valor desconocido → `llama`."""
    provider = (raw or "").strip().lower()
    if not provider:
        return "llama"
    if provider in LLM_PROVIDERS:
        return provider
    log.warning(
        "LLM_PROVIDER=%r desconocido (aceptados: %s); se usa 'llama'",
        raw,
        ", ".join(LLM_PROVIDERS),
    )
    return "llama"


def resolve_thinking_mode(raw):
    """Normaliza `LLM_THINKING_MODE`; cualquier valor desconocido → `auto`."""
    mode = (raw or "").strip().lower()
    if not mode:
        return "auto"
    if mode in LLM_THINKING_MODES:
        return mode
    log.warning(
        "LLM_THINKING_MODE=%r desconocido (aceptados: %s); se usa 'auto'",
        raw,
        ", ".join(LLM_THINKING_MODES),
    )
    return "auto"


def default_max_tokens_field(provider):
    """Campo del payload para el toque de salida según el perfil."""
    return "max_completion_tokens" if provider == "openai" else "max_tokens"


def normalize_base_url(base_url):
    """Raíz del servidor sin barra final (admite `.../v1` o la raíz)."""
    return (base_url or "").rstrip("/")


def chat_completions_url(base_url):
    """URL de chat tolerante a bases con o sin prefijo `/v1`."""
    base = normalize_base_url(base_url)
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def health_check_url(provider, base_url):
    """URL de salud según el perfil.

    llama-server expone `/health` en la RAÍZ (nunca bajo `/v1`); las APIs
    remotas validan credenciales con `GET /v1/models`.
    """
    base = normalize_base_url(base_url)
    if provider == "llama":
        root = base[:-3] if base.endswith("/v1") else base
        return f"{root}/health"
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


@dataclass(frozen=True)
class LlmConfig:
    """Configuración del backend LLM leída del entorno (una sola vez)."""

    provider: str = "llama"
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    max_tokens_field: str = "max_tokens"
    skip_temperature: bool = False
    response_format: bool = True
    health_check: bool = True
    thinking_mode: str = "auto"

    @classmethod
    def from_env(cls) -> "LlmConfig":
        """Construye la config desde el env (respetando alias históricos)."""
        provider = resolve_provider(os.environ.get("LLM_PROVIDER"))
        return cls(
            provider=provider,
            base_url=normalize_base_url(
                _env_str("LLM_BASE_URL", default=DEFAULT_BASE_URL)
            ),
            api_key=_env_str("LLM_API_KEY", "OPENAI_API_KEY"),
            model=_env_str("LLM_MODEL", default=DEFAULT_MODEL),
            max_tokens_field=_env_str("LLM_MAX_TOKENS_FIELD")
            or default_max_tokens_field(provider),
            skip_temperature=_env_flag("LLM_SKIP_TEMPERATURE", False),
            response_format=_env_flag("LLM_RESPONSE_FORMAT", True),
            health_check=_env_flag("LLM_HEALTH_CHECK", True),
            thinking_mode=resolve_thinking_mode(
                os.environ.get("LLM_THINKING_MODE")
            ),
        )


def build_llm(
    session, *, timeout=None, base_url=None, model=None
) -> "HttpLlmClient":
    """Fábrica única del cliente LLM: config del entorno → adaptador.

    Los tres puntos de construcción del bot (conversation, glue de citas e
    identidad) pasan por aquí para que perfil, clave y rutas se configuren en
    un solo sitio. `base_url` y `model` explícitos (glue/tests/evaluación)
    pisan los del entorno.
    """
    cfg = LlmConfig.from_env()
    return HttpLlmClient(
        base_url or cfg.base_url,
        session,
        timeout=timeout,
        model=model or cfg.model,
        provider=cfg.provider,
        api_key=cfg.api_key,
        max_tokens_field=cfg.max_tokens_field,
        skip_temperature=cfg.skip_temperature,
        response_format=cfg.response_format,
        thinking_mode=cfg.thinking_mode,
    )


def _extract_error_message(body):
    """Extrae el mensaje del proveedor desde el cuerpo del error."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error:
            return error
        if data.get("message"):
            return str(data["message"])
    return (body or "").strip()


def _redact(text, api_key):
    """Elimina secretos (API key, `Bearer ...`, `sk-...`) de un texto."""
    if api_key:
        text = text.replace(api_key, "***")
    text = re.sub(r"(?i)\bbearer\s+\S+", "Bearer ***", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_\-]{6,}", "sk-***", text)
    return text


async def _error_detail(response, api_key):
    """Cuerpo del error saneado y truncado (nunca la clave, en una línea)."""
    try:
        raw = await response.text()
    except Exception:  # noqa: BLE001 - el detalle es mejor esfuerzo
        return "(sin cuerpo de error)"
    detail = " ".join(_redact(_extract_error_message(raw), api_key).split())
    if not detail:
        return "(cuerpo vacío)"
    if len(detail) > _ERROR_DETAIL_LIMIT:
        return detail[:_ERROR_DETAIL_LIMIT] + "…"
    return detail


async def health_check(
    session, *, provider, base_url, enabled=True, timeout=5
) -> bool:
    """Comprueba el backend antes de un turno.

    - `enabled=False`: sin petición (True).
    - Perfil `llama`: el fallo se propaga (comportamiento histórico: el turno
      se aborta y se contesta con el aviso de «no puedo conectar»).
    - Perfiles remotos: el fallo de salud NUNCA bloquea el turno; se registra
      un warning y se continúa (el error real lo dirá la llamada al chat).
    """
    if not enabled:
        return True
    url = health_check_url(provider, base_url)
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as response:
            status = getattr(response, "status", 200)
            if provider == "llama":
                response.raise_for_status()
                return True
            if isinstance(status, int) and status >= 400:
                log.warning(
                    "Health check remoto devolvió HTTP %s (%s); se continúa el turno",
                    status,
                    url,
                )
                return False
            return True
    except (aiohttp.ClientError, asyncio.TimeoutError):
        if provider == "llama":
            raise
        log.warning(
            "Health check remoto inaccesible (%s); se continúa el turno", url
        )
        return False


class HttpLlmClient:
    """Implementa `airi.ports.llm.LLMClient` sobre una API Chat Completions."""

    def __init__(
        self,
        base_url: str,
        session: aiohttp.ClientSession,
        *,
        model: str | None = None,
        timeout: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        max_tokens_field: str | None = None,
        skip_temperature: bool | None = None,
        response_format: bool | None = None,
        thinking_mode: str | None = None,
    ):
        self.base_url = normalize_base_url(base_url)
        self.session = session
        self.model = model or os.environ.get(
            "LLM_MODEL", "Qwen3.6-35B-A3B-MTP-UD-IQ3_S"
        )
        if timeout is not None:
            self.timeout = timeout
        else:
            try:
                self.timeout = int(os.environ.get("LLM_TIMEOUT", "300"))
            except (ValueError, TypeError):
                log.warning("LLM_TIMEOUT tiene valor inválido, usando 300")
                self.timeout = 300
        if max_output_tokens is not None:
            self.max_output_tokens = max_output_tokens
        else:
            self.max_output_tokens = env_int("LLM_MAX_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS)
        if temperature is not None:
            self.temperature = temperature
        else:
            try:
                self.temperature = float(os.environ.get("LLM_TEMPERATURE", "0.6"))
            except (ValueError, TypeError):
                log.warning("LLM_TEMPERATURE tiene valor inválido, usando 0.6")
                self.temperature = 0.6
        # Perfil de compatibilidad y diferencias de payload (ver LlmConfig).
        self.provider = resolve_provider(
            provider if provider is not None else os.environ.get("LLM_PROVIDER")
        )
        self.api_key = (
            api_key
            if api_key is not None
            else _env_str("LLM_API_KEY", "OPENAI_API_KEY")
        )
        self.max_tokens_field = (
            max_tokens_field
            or _env_str("LLM_MAX_TOKENS_FIELD")
            or default_max_tokens_field(self.provider)
        )
        self.skip_temperature = (
            skip_temperature
            if skip_temperature is not None
            else _env_flag("LLM_SKIP_TEMPERATURE", False)
        )
        self.response_format = (
            response_format
            if response_format is not None
            else _env_flag("LLM_RESPONSE_FORMAT", True)
        )
        self.thinking_mode = resolve_thinking_mode(
            thinking_mode
            if thinking_mode is not None
            else os.environ.get("LLM_THINKING_MODE")
        )

    async def post(self, payload: dict) -> dict:
        """POST a la ruta de chat normalizada (devuelve la respuesta completa).

        El servidor es multi-modelo y exige `model`; se inyecta sin mutar el
        dict del llamador (si ya trae `model`, se respeta el suyo). Si hay API
        key se envía `Authorization: Bearer ...` — la cabecera y la clave
        jamás se registran en los logs.
        """
        url = chat_completions_url(self.base_url)
        payload = {"model": self.model, **payload}
        kwargs: dict = {"timeout": aiohttp.ClientTimeout(total=self.timeout)}
        if self.api_key:
            kwargs["headers"] = {"Authorization": f"Bearer {self.api_key}"}
        async with self.session.post(url, json=payload, **kwargs) as response:
            status = getattr(response, "status", 200)
            if isinstance(status, int) and status >= 400:
                detail = await _error_detail(response, self.api_key)
                log.error(
                    "Proveedor LLM %r devolvió HTTP %s en %s: %s",
                    self.provider,
                    status,
                    url,
                    detail,
                )
            response.raise_for_status()
            return await response.json()

    async def chat(self, messages, *, schema=None, max_tokens=None, temperature=None,
                   disable_thinking: bool = False,
                   force_disable_thinking: bool = False,
                   strict_schema: bool = False):
        content, _meta = await self.chat_with_meta(
            messages, schema=schema, max_tokens=max_tokens, temperature=temperature,
            disable_thinking=disable_thinking,
            force_disable_thinking=force_disable_thinking,
            strict_schema=strict_schema,
        )
        return content

    async def chat_with_meta(self, messages, *, schema=None, max_tokens=None,
                             temperature=None, disable_thinking: bool = False,
                             force_disable_thinking: bool = False,
                             strict_schema: bool = False, stream: bool = False):
        payload = {
            "model": self.model,
            "messages": messages,
            self.max_tokens_field: max_tokens or self.max_output_tokens,
            "stream": bool(stream),
        }
        if not self.skip_temperature:
            payload["temperature"] = (
                self.temperature if temperature is None else temperature
            )
        if stream and self.provider in ("llama", "openai"):
            # Sin esto el servidor no manda `usage` en SSE y el conteo de
            # tokens de una corrida en streaming queda desconocido.
            payload["stream_options"] = {"include_usage": True}
        if schema is not None:
            if not self.response_format:
                log.debug("response_format omitido (LLM_RESPONSE_FORMAT=0)")
            elif strict_schema:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_output",
                        "strict": True,
                        "schema": schema,
                    },
                }
            else:
                payload["response_format"] = {"type": "json_object"}
        # Extensión propietaria de llama.cpp/vLLM: fuera del perfil `llama`
        # OpenAI y compatibles la rechazarían.
        # `LLM_THINKING_MODE` pisa lo que pida el servicio: `on` nunca apaga el
        # razonamiento y `off` lo apaga en todos los turnos.
        if self.provider == "llama":
            if self.thinking_mode == "off":
                disable_thinking = True
            elif self.thinking_mode == "on":
                # El modo global manda en llamadas normales. Las reparaciones
                # clasificadas pueden solicitar un override solo para esta POST.
                disable_thinking = bool(force_disable_thinking)
            elif force_disable_thinking:
                disable_thinking = True
        if disable_thinking and self.provider == "llama":
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if stream:
            return await self._chat_with_meta_stream(payload)
        data = await self.post(payload)
        choices = data.get("choices") or []
        if not choices:
            log.error("El servidor no devolvió choices")
            return "", LLMMeta()
        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        meta = LLMMeta(
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage"),
            server_timings=_numeric_timings(data.get("timings")),
            reasoning_present=(
                bool(message.get("reasoning_content"))
                if isinstance(message.get("reasoning_content"), str)
                else None
            ),
            reasoning_tokens=_reasoning_token_count(data.get("usage")),
        )
        return text, meta

    async def _chat_with_meta_stream(self, payload):
        """Lee SSE; ensambla content para el parser y nunca retiene reasoning."""
        url = chat_completions_url(self.base_url)
        kwargs: dict = {"timeout": aiohttp.ClientTimeout(total=self.timeout)}
        if self.api_key:
            kwargs["headers"] = {"Authorization": f"Bearer {self.api_key}"}
        started = time.perf_counter()
        async with self.session.post(url, json=payload, **kwargs) as response:
            response.raise_for_status()
            content_parts = []
            usage = None
            finish_reason = None
            server_timings = None
            reasoning_present = None
            reasoning_deltas = 0
            content_deltas = 0
            ttft_ms = None
            first_content_ms = None
            done = False
            async for data in _iter_sse_data(response.content):
                if data.strip() == "[DONE]":
                    done = True
                    break
                try:
                    event = json.loads(data)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("Evento SSE JSON inválido") from exc
                if not isinstance(event, dict):
                    continue
                if event.get("error") is not None:
                    raise ValueError("El stream SSE devolvió un evento de error")
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                timings = _numeric_timings(event.get("timings"))
                if timings:
                    server_timings = timings
                choices = event.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason") is not None:
                    finish_reason = choice["finish_reason"]
                delta = choice.get("delta") or {}
                if not isinstance(delta, dict):
                    continue
                reasoning = delta.get("reasoning_content")
                has_reasoning = isinstance(reasoning, str) and bool(reasoning)
                if has_reasoning:
                    reasoning_present = True
                    reasoning_deltas += 1
                content = delta.get("content")
                has_content = isinstance(content, str) and bool(content)
                if has_content:
                    content_deltas += 1
                if (
                    (ttft_ms is None and (has_reasoning or has_content))
                    or (first_content_ms is None and has_content)
                ):
                    elapsed_ms = int(round((time.perf_counter() - started) * 1000))
                    if ttft_ms is None:
                        ttft_ms = elapsed_ms
                    if first_content_ms is None and has_content:
                        first_content_ms = elapsed_ms
                if has_content:
                    content_parts.append(content)
            if not done:
                raise ValueError("Stream SSE terminó sin el marcador [DONE]")
        return "".join(content_parts), LLMMeta(
            finish_reason=finish_reason,
            usage=usage or {},
            ttft_ms=ttft_ms,
            first_content_ms=first_content_ms,
            server_timings=server_timings,
            reasoning_present=reasoning_present,
            reasoning_tokens=_reasoning_token_count(usage),
            reasoning_deltas=reasoning_deltas,
            content_deltas=content_deltas,
        )
