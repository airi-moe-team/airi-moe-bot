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
from dataclasses import dataclass

import aiohttp

from airi.domain.constants import env_flag, env_int
from airi.ports.llm import LLMMeta

log = logging.getLogger(__name__)

DEFAULT_MAX_OUTPUT_TOKENS = 8000
#: URL por defecto: raíz de un llama-server local (alias histórico `LLAMA_URL`).
DEFAULT_BASE_URL = "http://127.0.0.1:8081"
#: Modelo por defecto (GGUF local); en perfiles remotos debe configurarse.
DEFAULT_MODEL = "Qwen3.6-35B-A3B-MTP-UD-IQ3_S"
#: Perfiles de compatibilidad soportados.
LLM_PROVIDERS = ("llama", "openai", "openai-compatible")

_ERROR_DETAIL_LIMIT = 300


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

    @classmethod
    def from_env(cls) -> "LlmConfig":
        """Construye la config desde el env (respetando alias históricos)."""
        provider = resolve_provider(os.environ.get("LLM_PROVIDER"))
        return cls(
            provider=provider,
            base_url=normalize_base_url(
                _env_str("LLM_BASE_URL", "LLAMA_URL", default=DEFAULT_BASE_URL)
            ),
            api_key=_env_str("LLM_API_KEY", "OPENAI_API_KEY"),
            model=_env_str("LLM_MODEL", default=DEFAULT_MODEL),
            max_tokens_field=_env_str("LLM_MAX_TOKENS_FIELD")
            or default_max_tokens_field(provider),
            skip_temperature=_env_flag("LLM_SKIP_TEMPERATURE", False),
            response_format=_env_flag("LLM_RESPONSE_FORMAT", True),
            health_check=_env_flag("LLM_HEALTH_CHECK", True),
        )


def build_llm(session, *, timeout=None, base_url=None) -> "HttpLlmClient":
    """Fábrica única del cliente LLM: config del entorno → adaptador.

    Los tres puntos de construcción del bot (conversation, glue de citas e
    identidad) pasan por aquí para que perfil, clave y rutas se configuren en
    un solo sitio. `base_url` explícito (glue/tests) pisa el del entorno.
    """
    cfg = LlmConfig.from_env()
    return HttpLlmClient(
        base_url or cfg.base_url,
        session,
        timeout=timeout,
        model=cfg.model,
        provider=cfg.provider,
        api_key=cfg.api_key,
        max_tokens_field=cfg.max_tokens_field,
        skip_temperature=cfg.skip_temperature,
        response_format=cfg.response_format,
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
                   disable_thinking: bool = False, strict_schema: bool = False):
        content, _meta = await self.chat_with_meta(
            messages, schema=schema, max_tokens=max_tokens, temperature=temperature,
            disable_thinking=disable_thinking, strict_schema=strict_schema,
        )
        return content

    async def chat_with_meta(self, messages, *, schema=None, max_tokens=None,
                             temperature=None, disable_thinking: bool = False,
                             strict_schema: bool = False):
        payload = {
            "model": self.model,
            "messages": messages,
            self.max_tokens_field: max_tokens or self.max_output_tokens,
            "stream": False,
        }
        if not self.skip_temperature:
            payload["temperature"] = (
                self.temperature if temperature is None else temperature
            )
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
        if disable_thinking and self.provider == "llama":
            payload["chat_template_kwargs"] = {"enable_thinking": False}
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
        )
        return text, meta
