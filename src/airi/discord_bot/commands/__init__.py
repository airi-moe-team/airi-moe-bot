"""Registro de comandos de la capa Discord."""

from airi.discord_bot.commands import (
    affinity,
    dates,
    debug,
    diary,
    gifts,
    identity,
    memories,
    ranking,
    reset,
    season,
    users,
)
from airi.discord_bot.commands import (
    help as help_cmd,
)
from airi.discord_bot.commands.registry import CommandRegistry
from airi.observability.instrumentation import traced
from airi.persona import current_persona


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    character_id = current_persona().id
    identity_alias = f"!identidad-{character_id}"
    mood_alias = f"!animo-{character_id}"
    # Cada handler se envuelve para dejar un `TurnEvent` (kind="command" por
    # defecto; !regalo usa kind="gift") en el TraceStore compartido.
    command = traced("command")

    registry.exact("!ayuda", "!help")(command(help_cmd.handle))
    registry.exact("!afinidad")(command(affinity.handle_afinidad))
    registry.exact("!relacion")(command(affinity.handle_relacion))
    registry.exact("!ranking")(command(ranking.handle))
    registry.exact("!cita")(command(dates.handle))
    registry.exact("!reiniciar-temporada", "!reiniciar_temporada")(command(season.handle))
    registry.exact("!reset")(command(reset.handle))
    registry.exact(identity_alias, "!yo")(command(identity.handle_yo))
    registry.exact(mood_alias, "!animo")(command(identity.handle_animo))
    registry.exact("!descubrir")(command(identity.handle_descubrir))
    registry.exact("!descubrimientos")(command(identity.handle_descubrimientos))
    registry.prefix(f"{identity_alias} historia", "!yo historia")(
        command(identity.handle_yo_historia)
    )
    registry.prefix(f"{identity_alias} revertir", "!yo revertir")(
        command(identity.handle_yo_revertir)
    )

    registry.prefix("!regalo")(traced("gift")(gifts.handle))
    registry.prefix("!memorias")(command(memories.handle_memorias))
    registry.prefix("!olvidar")(command(memories.handle_olvidar))
    registry.prefix("!diario")(command(diary.handle))
    registry.prefix("!usuarios")(command(users.handle))
    # !debug NO se instrumenta: inspecciona el ring y no debe ensuciarlo
    # (si no, `!debug clear` nunca dejaría el ring vacío).
    registry.prefix("!debug")(debug.handle)

    return registry


__all__ = ["CommandRegistry", "build_registry"]
