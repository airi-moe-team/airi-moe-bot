"""Búsqueda web con Brave Search API.

Devuelve notas estructuradas, sin URLs ni ranking: la presentación al modelo
es responsabilidad de ``airi.domain.web_tool``.
"""

from __future__ import annotations

import asyncio
import logging
import re

import aiohttp

from airi.ports.web_search import WebResult, WebSearchNotes

log = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

_URL = re.compile(r"https?://\S+", re.IGNORECASE)


def _clean(text, limit):
    text = _URL.sub("", str(text or ""))
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


class BraveSearchClient:
    """Implementa `airi.ports.web_search.WebSearchClient`."""

    def __init__(
        self,
        api_key: str,
        session: aiohttp.ClientSession,
        *,
        max_results: int = 5,
        url: str = BRAVE_SEARCH_URL,
        timeout: int = 15,
    ):
        self.api_key = api_key or ""
        self.session = session
        self.max_results = max_results
        self.url = url
        self.timeout = timeout

    async def search(self, query):
        if not self.api_key:
            log.error("BRAVE_API_KEY no configurada; no se puede buscar")
            return None

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }
        params = {
            "q": query,
            "count": self.max_results,
            "safesearch": "moderate",
            "text_decorations": "false",
            "extra_snippets": "true",
        }

        try:
            async with self.session.get(
                self.url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                log.info("Brave HTTP %s para query %r", response.status, query)
                if response.status == 401:
                    log.error("Brave: API key inválida o no autorizada (401)")
                    return None
                if response.status == 429:
                    log.warning("Brave: rate limit alcanzado (429)")
                    return None
                if response.status != 200:
                    body = (await response.text())[:300]
                    log.warning("Brave HTTP %s: %s", response.status, body)
                    return None
                data = await response.json()
        except asyncio.TimeoutError:
            log.warning("Timeout consultando Brave Search")
            return None
        except aiohttp.ClientError:
            log.exception("Error HTTP consultando Brave Search")
            return None
        except Exception:
            log.exception("Error inesperado con Brave Search")
            return None

        web_results = (data.get("web") or {}).get("results") or []
        log.info("Brave devolvió %d resultados", len(web_results))

        results = []
        for result in web_results:
            if not isinstance(result, dict):
                continue
            title = _clean(result.get("title"), 200)
            description = _clean(result.get("description"), 500)
            extra = result.get("extra_snippets") or []
            if extra:
                description = _clean(
                    description
                    + " "
                    + " ".join(s for s in extra if isinstance(s, str)),
                    700,
                )
            if not title and not description:
                continue
            results.append(WebResult(title=title, snippet=description))
            if len(results) >= self.max_results:
                break

        if not results:
            log.warning("Brave devolvió resultados pero todos fueron descartados")
            return WebSearchNotes(())

        log.info(
            "Notas web listas (%d resultados). Primeras 300:\n%s",
            len(results),
            "\n".join(f"{r.title}: {r.snippet}" for r in results)[:300],
        )
        return WebSearchNotes(tuple(results))
