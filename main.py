import discord
from discord.ext import commands
import os, asyncio
import shutil
import ctypes.util

try:
    import nacl  # noqa: F401
    HAS_NACL = True
except Exception:
    HAS_NACL = False

#import all of the cogs
from help_cog import help_cog
from music_cog import music_cog

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix='?', intents=intents)

#remove the default help command so that we can write out own
bot.remove_command('help')


def ensure_opus_loaded() -> bool:
    if discord.opus.is_loaded():
        return True

    # Try common Linux/OpenSSL-compatible names first, then system discovery.
    candidates = [
        "libopus.so.0",
        "libopus.so",
        "opus",
        ctypes.util.find_library("opus"),
    ]

    for candidate in candidates:
        if not candidate:
            continue
        try:
            discord.opus.load_opus(candidate)
            return True
        except Exception:
            continue
    return False


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id={bot.user.id if bot.user else 'unknown'})")
    print(f"Connected to {len(bot.guilds)} guild(s)")


@bot.event
async def on_command_error(ctx, error):
    print(f"Command error from {ctx.author}: {error}")
    raise error

async def main():
    async with bot:
        await bot.add_cog(help_cog(bot))
        music = music_cog(bot)
        await bot.add_cog(music)
        token = os.getenv('TOKEN') or os.getenv('DISCORD_TOKEN')
        if not token:
            raise RuntimeError("Set TOKEN (or DISCORD_TOKEN) before starting the bot.")
        ffmpeg_binary = os.getenv('FFMPEG_PATH', 'ffmpeg')
        ffmpeg_path = shutil.which(ffmpeg_binary)
        if ffmpeg_path:
            print(f"FFmpeg detected at: {ffmpeg_path}")
        else:
            print(f"FFmpeg not found for binary: {ffmpeg_binary}")
        print(f"Music cog FFmpeg executable: {music.ffmpeg_executable}")
        print(f"PyNaCl available: {HAS_NACL}")
        opus_ok = ensure_opus_loaded()
        print(f"Opus loaded: {opus_ok}")
        print("Starting Discord bot connection...")
        await bot.start(token)

if __name__ == '__main__':
    asyncio.run(main())