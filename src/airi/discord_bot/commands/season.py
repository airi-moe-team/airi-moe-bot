"""Comando !reiniciar-temporada (solo OWNER_ID)."""

from __future__ import annotations

import logging

from airi.domain.relationships import reset_season_world
from airi.domain.self_notes import NOTES_KEY

log = logging.getLogger(__name__)


async def handle(ctx, message):
    if ctx.owner_id and message.author.id != ctx.owner_id:
        await message.reply(
            "Solo el dueño del canal puede reiniciar la temporada.",
            mention_author=False,
        )
        return

    lock = getattr(ctx, "lock", None)
    if lock is None:
        await _perform(ctx, message)
        return
    async with lock:
        await _perform(ctx, message)


async def _perform(ctx, message):
    state = ctx.state
    persistence = getattr(ctx, "persistence", None)
    archiver = getattr(ctx, "season_archiver", None)
    retention = getattr(ctx, "retention", None)
    season = int(state.world.get("season", 1) or 1)
    # El modo espectador olvida lo leído como espectadora al cerrar temporada.
    buffer = getattr(ctx, "passive_buffer", None)
    if buffer is not None:
        buffer.clear_all()

    try:
        archive_path = ""
        if persistence is not None and archiver is not None:
            archive_path = archiver.archive(
                season=season,
                aggregate=persistence.aggregate(),
            )

        if persistence is not None:
            with persistence.transaction():
                _mutate(state)
                if archive_path:
                    state.archive = {
                        "last_season": season,
                        "path": archive_path,
                    }
                persistence.save()
        else:
            _mutate(state)
            _save_all(state)
    except Exception as exc:
        log.exception("No se pudo reiniciar la temporada")
        await message.reply(
            "No pude reiniciar la temporada; no he cambiado nada. "
            f"Motivo: {type(exc).__name__}.",
            mention_author=False,
        )
        return

    if retention is not None:
        try:
            retention.prune()
        except Exception:
            log.exception("La retención posterior al reinicio falló")

    await message.channel.send(
        "💞 Nueva temporada: el corazón de Airi vuelve a estar libre. "
        "¡Que empiece la conquista!"
    )


def _mutate(state) -> None:
    state.world["winner_id"] = None
    state.world["relationship_started_at"] = None
    state.world["season"] = int(state.world.get("season", 1) or 1) + 1
    # Nueva temporada: las propuestas pendientes se cancelan y la etapa vuelve a
    # neutra. El historial confirmado se conserva (y queda en el archivo).
    reset_season_world(state.world)
    for uid, entry in state.affinity.items():
        if str(uid).startswith("_") or not isinstance(entry, dict):
            continue
        entry["points"] = 0
        entry["milestones"] = []
    # Nueva temporada: Airi no recuerda a nadie. Los nombres, fechas y
    # contadores de interacción se inyectan en el prompt, así que se borran
    # los registros activos; la copia de la temporada anterior queda archivada.
    state.users.clear()
    # Identidad: se conservan rasgos, valores y manías (el "yo" tipado),
    # pero se olvidan los descubrimientos libres y el historial de cambios:
    # son texto narrativo que puede nombrar a personas de la temporada anterior.
    # Los gustos viven en `world["preferences"]` y no se tocan.
    self_model = state.world.get("self")
    if isinstance(self_model, dict):
        self_model.pop("discoveries", None)
        # Los gustos son legado: la fuente canónica sigue en world["preferences"].
        self_model.pop("tastes", None)
        self_model["history"] = []
    state.world[NOTES_KEY] = []
    state.dates.clear()
    state.memories.clear()
    state.histories.clear()
    state.diary.clear()


def _save_all(state) -> None:
    """Compatibilidad con estados sin fachada de persistencia (tests/legado)."""
    state.save_world()
    state.save_affinity()
    state.save_users()
    state.save_dates()
    state.save_memories()
    state.save_diary()
