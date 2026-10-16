"""Constructores de embeds de Discord (puros: datos → embed).

No contienen lógica de juego ni tocan el estado; solo presentan.
"""

from __future__ import annotations

import discord

from airi.domain.constants import DATE_MAX_SECONDS

GIF_EMBED_COLOR = discord.Color(0xFFB6D9)

DATE_HELP_MINUTES_PLACEHOLDER = "{DATE_MINUTES}"


def date_max_minutes():
    """Minutos de la cita con redondeo al alza (p. ej. 300 s → 5)."""
    try:
        total = int(DATE_MAX_SECONDS)
    except (TypeError, ValueError):
        total = 0
    return max(1, (total + 59) // 60)

HELP_TEXT = (
    "**🎯 Objetivo**\n"
    "Ser el primero en llegar a **100 de afinidad** con Airi. Al cruzarlos, ella "
    "te confesará su amor y seréis **novios**. Después nadie más puede conquistarla "
    "hasta que se reinicie la temporada.\n\n"

    "**💬 Cómo subir afinidad**\n"
    "Habla con ella; Airi decide ella misma cuándo sube o baja, de `-5` a `+5`.\n"
    "• Sube: humor, interés sincero, coqueteo sutil, recordar lo que le gusta y "
    "apoyarla en un mal momento.\n"
    "• Baja: groserías, presión, incomodidad o spam.\n"
    "• No hay cupo diario: depende de que de verdad la conquistes (o la "
    "decepciones). Si no hablas, pierdes **-1 al día**.\n\n"

    "**💗 Niveles**\n"
    "Desconocida → Conocida → Amiga → Interés → Enamorada → Novios\n\n"

    "**🎮 Comandos de usuario**\n"
    "• `!afinidad` — tus puntos y nivel\n"
    "• `!relacion` — vuestro estado (días juntos, etc.)\n"
    "• `!ranking` — quién va ganando\n"
    "• `!cita` — invitarla a una cita (nivel Amiga, 1 cada 6 h). Ella te "
    "pregunta adónde la llevas y tú escribes el lugar. Son varios turnos "
    f"(máx. ~{DATE_HELP_MINUTES_PLACEHOLDER} min) y en uno de ellos Airi te hará UNA pregunta importante: "
    "elígele respuesta con los botones y la afinidad puede subir o bajar "
    "muchísimo. Si la cosa se tuerce tendrás una última oportunidad para "
    "reconducirla. Mientras Airi está en una cita, nadie más puede "
    "hablarle hasta que termine.\n"
    "• `!regalo <item>` — regalarle algo (1/día). Prueba: flores, chocolate, collar...\n"
    "• `!memorias` / `!olvidar <número>` — ver o borrar sus recuerdos sobre ti\n"
    "• `!diario` — leer el diario de recuerdos de Airi\n"
    "• `!usuarios` — gente del canal\n"
    "• `!reset` — reiniciar vuestra conversación\n\n"

    "**🔧 Comandos de administrador**\n"
    "• `!reiniciar-temporada` — nueva temporada: resetea afinidad, recuerdos, "
    "diario y contadores de interacción\n"
    "• `!debug turno` / `!debug trace` — inspeccionar el último turno\n"
    "• `!debug ultimo [n]` — resumen de los últimos n eventos\n"
    "• `!debug id <cid>` — JSON crudo del evento con ese correlation_id\n"
    "• `!debug errores` — eventos recientes con errores\n"
    "• `!debug clear` — vacía el ring de eventos en memoria\n\n"

    "**💡 Trucos**\n"
    "Descubre sus gustos (flor y comida favoritas) y acierta con los regalos. "
    "Las citas suben la afinidad mucho más rápido."
)


def build_help_embed():
    description = HELP_TEXT.replace(
        DATE_HELP_MINUTES_PLACEHOLDER, str(date_max_minutes())
    )
    return discord.Embed(
        title="💘 Cómo conquistar a Airi",
        description=description,
        color=GIF_EMBED_COLOR,
    )


def affinity_embed(user, points, level_name, progress):
    embed = discord.Embed(
        title="💛 Afinidad con Airi",
        description=(
            f"{user.display_name} tiene **{points} puntos** de afinidad.\n"
            f"Nivel actual: **{level_name}**\n{progress}"
        ),
        color=GIF_EMBED_COLOR,
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    return embed


def relation_embed(user, estado, points, level_name, progress):
    embed = discord.Embed(
        title="💛 Tu relación con Airi",
        description=(
            f"{estado}\n\nNivel: **{level_name}**\n"
            f"Afinidad: **{points}** pts\n{progress}"
        ),
        color=GIF_EMBED_COLOR,
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    return embed


def ranking_embed(rows, status_line):
    medals = ("🥇", "🥈", "🥉")
    lines = []
    for i, row in enumerate(rows[:10]):
        pos = medals[i] if i < 3 else f"{i + 1}."
        crown = " 💍" if row["is_winner"] else ""
        lines.append(
            f"{pos} **{row['name']}** — {row['points']} pts · "
            f"{row['level']}{crown}"
        )
    return discord.Embed(
        title="💘 Ranking de pretendientes",
        description="\n".join(lines) + f"\n\n{status_line}",
        color=GIF_EMBED_COLOR,
    )


def memories_embed(listing):
    embed = discord.Embed(
        title="🧠 Memorias de Airi",
        description=listing,
        color=GIF_EMBED_COLOR,
    )
    embed.set_footer(
        text="Usa !olvidar <número> o !olvidar todo para borrar memorias"
    )
    return embed


def diary_embed(listing):
    embed = discord.Embed(
        title="📔 Diario de Airi",
        description=listing,
        color=GIF_EMBED_COLOR,
    )
    embed.set_footer(text="Los recuerdos de Airi, a la vista de todos")
    return embed


def users_embed(description):
    return discord.Embed(
        title="👋 Personas del canal",
        description=description,
        color=GIF_EMBED_COLOR,
    )
