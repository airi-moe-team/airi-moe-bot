"""Vistas de Discord para el sistema de citas de Airi.

Este módulo solo sabe de interfaz (embeds y botones). No importa `bot` ni
contiene lógica de juego: los callbacks (`on_scene`, `on_choice`) se inyectan
desde la capa de turno, lo que evita un import circular y mantiene separada la UI.

Regla de oro: la IA decide las situaciones y las opciones; aquí solo se
convierten en botones y se valida que quien pulsa sea el dueño de la cita.
Los botones se reservan para la ÚNICA pregunta decisiva de la cita.
"""

import discord

from airi.domain.constants import DATE_QUESTION_OPTIONS

DISCORD_LABEL_MAX = 80
DISCORD_MAX_BUTTONS = 25

DATE_EMBED_COLOR = discord.Color(0xF472B6)

DATE_QUESTION_EMOJIS = ("💗", "✨", "🌙")

DATE_SCENE_EMOJIS = ("🕯️", "🍿", "🎡")
DATE_SCENE_LABEL_MAX = 30
DATE_SCENE_STOPWORDS = frozenset(
    {"y", "e", "o", "u", "de", "del", "con", "a", "al", "en",
     "la", "el", "los", "las", "un", "una", "por", "para", "que"}
)


def clamp_label(text, limit=DISCORD_LABEL_MAX):
    """Normaliza una etiqueta a una sola línea y la recorta al límite de Discord."""
    text = " ".join(str(text or "").split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def scene_label(scene, limit=DATE_SCENE_LABEL_MAX):
    """Etiqueta de botón a partir de una escena: una línea, con mayúscula inicial y recortada.

    El recorte se hace en frontera de palabra y descarta conectores colgantes al
    final, para que la etiqueta sea legible en móvil.
    """
    text = " ".join(str(scene or "").split())
    if text:
        text = text[:1].upper() + text[1:]
    if len(text) <= limit:
        return text
    head = text[: limit - 1].rstrip()
    if " " in head:
        head = head.rsplit(" ", 1)[0].rstrip()
    while " " in head and head.split()[-1].lower() in DATE_SCENE_STOPWORDS:
        head = head.rsplit(" ", 1)[0].rstrip()
    if not head:
        head = text[: limit - 1].rstrip()
    return head + "…"


def remaining_time_text(seconds_left):
    """Texto compacto del tiempo restante: `<1 min` o `~N min` (redondeo al alza)."""
    try:
        seconds = int(seconds_left)
    except (TypeError, ValueError):
        return None
    if seconds < 60:
        return "<1 min"
    return f"~{(seconds + 59) // 60} min"


def build_date_embed(
    reply,
    *,
    title=None,
    scene=None,
    state="active",
    turns_left=None,
    seconds_left=None,
    gif_url=None,
):
    """Embed que enmarca un turno de cita: respuesta de Airi + estado."""
    embed = discord.Embed(description=reply or "…", color=DATE_EMBED_COLOR)
    if title:
        embed.title = title
    elif scene:
        embed.title = f"🌹 Cita · {scene}"
    footer = []
    if state == "last_chance":
        footer.append("Última oportunidad")
    elif state == "closed":
        footer.append("Cita finalizada")
    if turns_left is not None:
        footer.append(f"Turnos restantes: {turns_left}")
    time_text = remaining_time_text(seconds_left)
    if time_text is not None:
        footer.append(f"⏳ {time_text}")
    if footer:
        embed.set_footer(text=" · ".join(footer))
    if gif_url:
        embed.set_image(url=gif_url)
    return embed


def build_question_embed(text):
    """Embed de la pregunta decisiva (la respuesta se elige con botones)."""
    embed = discord.Embed(
        title="💞 Airi te pregunta algo importante",
        description=text or "…",
        color=DATE_EMBED_COLOR,
    )
    embed.set_footer(text="Elige una respuesta con los botones.")
    return embed


class _PayloadButton(discord.ui.Button):
    """Botón que reenvía su payload al manejador de su vista."""

    def __init__(
        self,
        label,
        payload,
        *,
        style=discord.ButtonStyle.primary,
        emoji=None,
    ):
        super().__init__(label=clamp_label(label), style=style, emoji=emoji)
        self.payload = payload

    async def callback(self, interaction):
        await self.view.handle_choice(interaction, self.payload)


class _OwnerView(discord.ui.View):
    """Base: comprueba el dueño y deshabilita los botones al elegir."""

    def __init__(self, owner_id, *, timeout):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    def disable_all(self):
        for child in self.children:
            child.disabled = True

    async def handle_choice(self, interaction, payload):
        if interaction.user.id != self.owner_id:
            owner_mention = f"<@{self.owner_id}>"
            await interaction.response.send_message(
                f"Esa cita no es contigo, es de {owner_mention}~",
                ephemeral=True,
            )
            return
        self.disable_all()
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            pass
        await self.on_choice(interaction, payload)

    async def on_choice(self, interaction, payload):  # pragma: no cover - override
        raise NotImplementedError

    async def on_timeout(self):
        self.disable_all()
        message = getattr(self, "message", None)
        if message is None:
            return
        try:
            await message.edit(view=self)
        except discord.HTTPException:
            pass
        if getattr(self, "on_expire", None) is not None:
            result = self.on_expire()
            if hasattr(result, "__await__"):
                await result


class SceneSelectView(_OwnerView):
    """Selector inicial: hasta 3 planes (con emoji por posición) + "Sorpréndeme"."""

    def __init__(self, owner_id, scenes, on_choice, *, timeout=120):
        super().__init__(owner_id, timeout=timeout)
        self.on_choice = on_choice

        # Fila 1: opciones de escena
        for scene, emoji in zip(scenes, DATE_SCENE_EMOJIS):
            self.add_item(_PayloadButton(scene_label(scene), scene, emoji=emoji))

        # Fila 2: opción "dejar que el azar decida"
        self.add_item(
            _PayloadButton(
                "Sorpréndeme", None, emoji="🎲", style=discord.ButtonStyle.secondary
            )
        )


class DateQuestionView(_OwnerView):
    """Pregunta decisiva de la cita: una alternativa por botón.

    El payload es el ÍNDICE de la opción en `session["question"]["options"]`.
    """

    def __init__(self, owner_id, options, on_choice, *, timeout=180, on_expire=None):
        super().__init__(owner_id, timeout=timeout)
        self.on_choice = on_choice
        self.on_expire = on_expire
        limited = list(options or [])[:DATE_QUESTION_OPTIONS]
        for index, option in enumerate(limited):
            label = option.get("label") if isinstance(option, dict) else None
            fallback = option.get("action") if isinstance(option, dict) else None
            emoji = DATE_QUESTION_EMOJIS[index % len(DATE_QUESTION_EMOJIS)]
            self.add_item(
                _PayloadButton(
                    label or fallback or f"Opción {index + 1}", index, emoji=emoji
                )
            )
