import discord
from discord.ext import commands


class help_cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        prefix = self.bot.command_prefix if isinstance(self.bot.command_prefix, str) else "?"
        await self.bot.change_presence(activity=discord.Game(f"{prefix}help or /play"))

    @commands.command(name="help", help="Show available commands")
    async def help(self, ctx: commands.Context):
        prefix = self.bot.command_prefix if isinstance(self.bot.command_prefix, str) else "?"
        message = (
            "```\n"
            "Discord Music Bot Commands\n\n"
            "Slash:\n"
            "/play <query>\n"
            "/p <query>\n\n"
            "Prefix:\n"
            f"{prefix}play <query>\n"
            f"{prefix}p <query>\n"
            f"{prefix}queue\n"
            f"{prefix}skip\n"
            f"{prefix}pause\n"
            f"{prefix}resume\n"
            f"{prefix}remove\n"
            f"{prefix}clear\n"
            f"{prefix}stop\n"
            "```"
        )
        await ctx.send(message)
