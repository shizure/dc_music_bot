import discord
from discord.ext import commands
import os, asyncio

#import all of the cogs
from help_cog import help_cog
from music_cog import music_cog

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix='?', intents=intents)

#remove the default help command so that we can write out own
bot.remove_command('help')


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
        await bot.add_cog(music_cog(bot))
        token = os.getenv('TOKEN') or os.getenv('DISCORD_TOKEN')
        if not token:
            raise RuntimeError("Set TOKEN (or DISCORD_TOKEN) before starting the bot.")
        print("Starting Discord bot connection...")
        await bot.start(token)

if __name__ == '__main__':
    asyncio.run(main())