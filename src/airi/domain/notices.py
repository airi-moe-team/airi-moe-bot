"""Avisos de sistema de Airi (datos puros, sin dependencias de Discord).

Cada aviso lleva un ``kind`` estable para que la capa de presentación decida
título, emoji y color. El texto ya es el mensaje final que verá el canal.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Notice:
    """Aviso de un evento relevante ocurrido en el turno o en segundo plano."""

    kind: str
    text: str
    user_id: str | None = None
    dedupe_key: str = ""


def _uid(user_id):
    return None if user_id is None else str(user_id)


def meet_notice(display_name, *, user_id=None):
    name = display_name or "alguien"
    return Notice(
        "meet",
        f"Airi ha conocido a **{name}** por primera vez.",
        user_id=_uid(user_id),
        dedupe_key=f"meet:{_uid(user_id) or ''}",
    )


def discovery_notice(*, user_id=None):
    return Notice(
        "discovery",
        "Airi ha descubierto algo de sí misma.",
        user_id=_uid(user_id),
    )


def memory_saved_notice(*, user_id=None):
    return Notice(
        "memory_saved",
        "Airi recordará este evento",
        user_id=_uid(user_id),
    )


def self_changed_notice(*, user_id=None):
    return Notice(
        "self_changed",
        "Airi ha aprendido algo nuevo sobre sí misma.",
        user_id=_uid(user_id),
    )


def level_up_notice(display_name, level_name, *, user_id=None):
    name = display_name or "alguien"
    return Notice(
        "level_up",
        f"Airi siente algo más por **{name}**: vuestra relación ha subido a "
        f"**{level_name}**.",
        user_id=_uid(user_id),
        dedupe_key=f"level_up:{_uid(user_id) or ''}:{level_name}",
    )


def relationship_proposed_notice(display_name, *, user_id=None):
    name = display_name or "alguien"
    return Notice(
        "relationship_proposed",
        f"Airi le ha propuesto a **{name}** dar un paso más.",
        user_id=_uid(user_id),
        dedupe_key=f"relationship_proposed:{_uid(user_id) or ''}",
    )


def relationship_confirmed_notice(display_name, *, user_id=None):
    name = display_name or "alguien"
    return Notice(
        "relationship_confirmed",
        f"Airi y **{name}** ahora son pareja.",
        user_id=_uid(user_id),
        dedupe_key=f"relationship_confirmed:{_uid(user_id) or ''}",
    )


def web_search_notice():
    return Notice(
        "web_search",
        "Un momentito, estoy buscando información en la web...",
    )
