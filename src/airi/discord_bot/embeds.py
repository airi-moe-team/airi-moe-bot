"""Constructores de embeds de Discord (puros: datos → embed).

No contienen lógica de juego ni tocan el estado; solo presentan.
"""

from __future__ import annotations

import discord

from airi.domain.notices import Notice
from airi.persona import character_name

GIF_EMBED_COLOR = discord.Color(0xFFB6D9)

# Presentación de los avisos de dominio. El título ya incluye el emoji para
# que Discord lo muestre tal cual y las pruebas puedan comprobarlo.
NOTICE_STYLES = {
    "meet": ("🌙 Nuevo encuentro", discord.Color(0x89B4FA)),
    "discovery": ("✨ Descubrimiento", discord.Color(0xCBA6F7)),
    "memory_saved": ("📝 Memoria guardada", discord.Color(0xF9E2AF)),
    "self_changed": (
        f"🧠 {character_name()} ha aprendido algo nuevo",
        discord.Color(0xB4BEFE),
    ),
    "level_up": ("💗 Nivel de afinidad", discord.Color(0xF5C2E7)),
    "relationship_proposed": ("💍 Propuesta", discord.Color(0xF38BA8)),
    "relationship_confirmed": ("💞 Pareja confirmada", discord.Color(0xF38BA8)),
    "web_search": ("🔎 Buscando en la web", discord.Color(0x89B4FA)),
}


def system_embed(description, *, title=None, color=None):
    """Embed neutro para avisos de sistema y resultados de comandos."""
    return discord.Embed(
        title=title,
        description=description,
        color=color or GIF_EMBED_COLOR,
    )


def connected_embed():
    """Aviso de que Airi ha vuelto a estar disponible."""
    return system_embed(
        f"{character_name()} está en línea.",
        title=f"🟢 {character_name()} se ha conectado",
    )


def disconnecting_embed(reason):
    """Aviso de cierre con el motivo personal (solo canal de origen)."""
    clean = str(reason or "").strip()[:300]
    body = (
        f"«{clean}»\n\n{character_name()} está cerrando los ojitos y desconectándose por un ratito. Se acurruca y se queda dormida. No hagan mucho ruido... ¡que luego le cuesta levantarse!"
        if clean
        else f"{character_name()} está cerrando los ojitos y desconectándose por un ratito. Se acurruca y se queda dormida. No hagan mucho ruido... ¡que luego le cuesta levantarse!"
    )
    return system_embed(body, title=f"🚪 {character_name()} se está desconectando")


def notice_embed(notice):
    """Embed para avisos post-turno (memoria, identidad, etc.).

    Acepta `Notice` para elegir título y color según el evento, y también
    cadenas sueltas (avisos de fecha u otros flujos antiguos) con el estilo
    genérico de Airi.
    """
    if isinstance(notice, Notice):
        title, color = NOTICE_STYLES.get(
            notice.kind, (f"💗 {character_name()}", GIF_EMBED_COLOR)
        )
        return system_embed(notice.text, title=title, color=color)
    return system_embed(str(notice), title=f"💗 {character_name()}")

HELP_TEXT = (
    "**🎯 Objetivo**\n"
    f"Conocer a {character_name()} y construir un vínculo real con ella. La **afinidad** mide "
    "cercanía y confianza (máx. 100), pero no convierte a nadie en pareja: sus "
    "sentimientos avanzan solo con momentos concretos que pueda recordar y una "
    "pareja requiere una propuesta y una aceptación mutua.\n\n"

    "**💬 Cómo subir afinidad**\n"
    f"Habla con ella; {character_name()} decide ella misma cuándo sube o baja, de `-5` a `+5`.\n"
    "• Sube: humor, interés sincero, recordar lo que le gusta y apoyarla en un "
    "mal momento.\n"
    "• Baja: groserías, presión, incomodidad o spam.\n"
    "• No hay cupo diario: depende de que de verdad conectéis. Si no hablas, "
    "pierdes **-1 al día**.\n\n"

    "**💗 Niveles de cercanía**\n"
    "Desconocida → Conocida → Amiga → Cercana → Muy cercana → Inseparables\n"
    "Los niveles altos son cercanía social; el romance depende de su etapa "
    "afectiva y de la evidencia de lo vivido.\n\n"

    "**🎮 Comandos de usuario**\n"
    "• `!afinidad` — tus puntos y nivel\n"
    "• `!relacion` — vuestro estado (días juntos, etc.)\n"
    "• `!ranking` — quién va ganando\n"
    "• `!cita` — invitarla a una cita (nivel Amiga, 1 cada 6 h). Son varios "
    "turnos (máx. ~5 min): si la cosa se tuerce tendrás una última oportunidad "
    f"para reconducirla. Mientras {character_name()} está en una cita, nadie más puede "
    "hablarle hasta que termine.\n"
    "• `!regalo <item>` — regalarle algo (1/día). Prueba: flores, chocolate, collar...\n"
    "• `!memorias` / `!olvidar <número>` — ver o borrar sus recuerdos sobre ti\n"
    f"• `!diario` — ver los recuerdos de {character_name()} sobre ti; `!diario todos` (solo dueño, por DM)\n"
    "• `!usuarios` — gente del canal\n"
    f"• `!yo` — ver cómo es {character_name()} ahora mismo\n"
    "• `!animo` — ver su ánimo actual y la evolución de los últimos turnos\n"
    f"• `!yo historia` — cambios que {character_name()} ha hecho en su forma de ser\n"
    f"• `!descubrir` — pedirle a {character_name()} una reflexión sobre sí misma (solo dueño)\n"
    "• `!descubrimientos` — ver sus descubrimientos privados (solo dueño)\n"
    "• `!reset` — reiniciar vuestra conversación\n\n"

    "**🔧 Comandos de administrador**\n"
    "• `!reiniciar-temporada` — nueva temporada: olvida usuarios, afinidad, "
    "recuerdos y diario\n"
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
    return discord.Embed(
        title=f"💘 Cómo conquistar a {character_name()}",
        description=HELP_TEXT,
        color=GIF_EMBED_COLOR,
    )


def affinity_embed(user, points, level_name, progress):
    embed = discord.Embed(
        title=f"💛 Afinidad con {character_name()}",
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
        title=f"💛 Tu relación con {character_name()}",
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
        title=f"🧠 Memorias de {character_name()}",
        description=listing,
        color=GIF_EMBED_COLOR,
    )
    embed.set_footer(
        text="Usa !olvidar <número> o !olvidar todo para borrar memorias"
    )
    return embed


def diary_embed(listing, *, footer=f"Recuerdos de {character_name()} relacionados contigo"):
    embed = discord.Embed(
        title=f"📔 Diario de {character_name()}",
        description=listing,
        color=GIF_EMBED_COLOR,
    )
    embed.set_footer(text=footer)
    return embed


def users_embed(description):
    return discord.Embed(
        title="👋 Personas del canal",
        description=description,
        color=GIF_EMBED_COLOR,
    )


def scene_select_embed(color):
    return discord.Embed(
        title="🌹 ¿Adónde la llevas?",
        description=(
            "👇 Elige un plan o déjate llevar por el azar."
        ),
        color=color,
    )


def date_prompt_embed(color):
    return discord.Embed(
        title="💭 ¿Qué haces?",
        description=(
            "👇 Elige una acción, o escribe con tus propias palabras lo que quieras hacer~"
        ),
        color=color,
    )
