import asyncio
import os

import discord
from discord.ext import commands

from help_cog import help_cog
from music_cog import music_cog


intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.message_content = True

prefix = os.getenv("BOT_PREFIX", "?")
bot = commands.Bot(command_prefix=prefix, intents=intents, help_command=None)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id={bot.user.id if bot.user else 'unknown'})")
    print(f"Connected to {len(bot.guilds)} guild(s)")

    if getattr(bot, "_slash_synced", False):
        return

    guild_id = os.getenv("DISCORD_GUILD_ID") or os.getenv("GUILD_ID")
    try:
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Synced {len(synced)} slash command(s) to guild {guild_id}")
        else:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} global slash command(s)")
        bot._slash_synced = True
    except Exception as exc:
        print(f"Slash command sync failed: {exc}")


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"Command error from {ctx.author}: {error}")


async def main():
    token = os.getenv("TOKEN") or os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Set TOKEN or DISCORD_TOKEN before starting the bot.")

    async with bot:
        await bot.add_cog(help_cog(bot))
        music = music_cog(bot)
        await bot.add_cog(music)

        print(f"Lavalink URI: {music.lavalink_uri}")
        print(f"Lavalink search prefix: {music.lavalink_search_prefix}")

        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
