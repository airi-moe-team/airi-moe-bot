"""Dobles falsos de búsqueda, GIFs, notificador y usuario."""

from __future__ import annotations

from airi.ports.web_search import WebResult, WebSearchNotes


def _notes(result):
    """Acepta notas, texto libre (tests antiguos) o None."""
    if result is None or isinstance(result, WebSearchNotes):
        return result
    if isinstance(result, str):
        return WebSearchNotes((WebResult("", result),))
    if isinstance(result, (list, tuple)):
        return WebSearchNotes(tuple(result))
    return result


class FakeSearch:
    """Implementa `airi.ports.web_search.WebSearchClient`."""

    def __init__(self, result=None):
        self.result = _notes(result)
        self.queries = []

    async def search(self, query):
        self.queries.append(query)
        return self.result


class FakeGif:
    """Implementa `airi.ports.gif_provider.GifProvider`."""

    def __init__(self, data=b"GIF89a-fake"):
        self.data = data
        self.requested = []

    async def fetch(self, kind):
        self.requested.append(kind)
        if kind == "none":
            return None
        return self.data


class FakeNotifier:
    """Implementa `airi.ports.notifier.Notifier` capturando los mensajes."""

    def __init__(self):
        self.sent = []

    async def send(self, content):
        self.sent.append(content)


class FakeUser:
    """Sustituto mínimo de `discord.User` para los servicios."""

    def __init__(self, user_id, display_name):
        self.id = user_id
        self.display_name = display_name
        self.display_avatar = type("Avatar", (), {"url": ""})()
