import discord
from discord.ext import commands
import os, asyncio

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='?', intents=intents)

@bot.command()
async def join(ctx):
    print(f"Attempting to join: {ctx.author.voice.channel}")
    vc = await ctx.author.voice.channel.connect()
    print(f"Connected: {vc}")

bot.run(os.getenv('TOKEN'))