"""Comando !reset (reinicia la conversación de ese usuario)."""

from airi.discord_bot import embeds


async def handle(ctx, message):
    ctx.reset_conversation(message.channel.id, message.author.id)
    await message.reply(
        embed=embeds.system_embed(
            "¡Listo! He reiniciado nuestra conversación. ¡Empezamos de nuevo!"
        ),
        mention_author=False,
    )
