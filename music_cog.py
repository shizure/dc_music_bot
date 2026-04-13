from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import deque
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands
import wavelink


URL_RE = re.compile(r"^https?://", re.IGNORECASE)


@dataclass
class QueueItem:
    track: wavelink.Playable
    title: str


@dataclass
class GuildState:
    queue: deque[QueueItem] = field(default_factory=deque)
    current: QueueItem | None = None
    status_channel_id: int | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class music_cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._logger = logging.getLogger(__name__)
        self._states: dict[int, GuildState] = {}
        self._node_ready = False

        self.lavalink_uri = os.getenv("LAVALINK_URI", "http://localhost:2333")
        self.lavalink_password = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
        self.lavalink_search_prefix = os.getenv("LAVALINK_SEARCH_PREFIX", "ytmsearch")

    def _state(self, guild_id: int) -> GuildState:
        if guild_id not in self._states:
            self._states[guild_id] = GuildState()
        return self._states[guild_id]

    async def _connect_lavalink(self) -> None:
        if self._node_ready:
            return

        try:
            existing_nodes = getattr(wavelink.Pool, "nodes", None)
            if existing_nodes:
                self._node_ready = True
                return
        except Exception:
            pass

        node = wavelink.Node(uri=self.lavalink_uri, password=self.lavalink_password)
        await wavelink.Pool.connect(nodes=[node], client=self.bot)
        self._node_ready = True

    async def _ensure_node(self) -> None:
        try:
            await self._connect_lavalink()
        except Exception as exc:
            raise RuntimeError(
                "Lavalink is not reachable. Check LAVALINK_URI and LAVALINK_PASSWORD."
            ) from exc

    async def _get_player(self, member: discord.Member) -> wavelink.Player:
        voice_state = getattr(member, "voice", None)
        channel = getattr(voice_state, "channel", None)
        if channel is None:
            raise RuntimeError("You need to join a voice channel first.")

        guild = member.guild
        existing = guild.voice_client

        if existing and isinstance(existing, wavelink.Player):
            player = existing
            if player.channel and player.channel.id != channel.id:
                try:
                    await player.move_to(channel)
                except Exception:
                    await player.disconnect()
                    player = await channel.connect(cls=wavelink.Player, self_deaf=True)
            return player

        if existing:
            try:
                await existing.disconnect()
            except Exception:
                pass

        player = await channel.connect(cls=wavelink.Player, self_deaf=True)
        return player

    async def _search_track(self, query: str) -> QueueItem:
        value = query.strip()
        if not value:
            raise RuntimeError("Please provide a song name or a URL.")

        search_attempts: list[str]
        if URL_RE.match(value):
            search_attempts = [value]
        else:
            raw_prefixes = [self.lavalink_search_prefix, "ytmsearch", "ytsearch"]
            prefixes: list[str] = []
            for prefix in raw_prefixes:
                cleaned = prefix.strip().lower()
                if not cleaned or cleaned in prefixes:
                    continue
                prefixes.append(cleaned)
            search_attempts = [f"{prefix}:{value}" for prefix in prefixes]

        last_error: Exception | None = None
        for search_value in search_attempts:
            try:
                results = await wavelink.Playable.search(search_value)
            except Exception as exc:
                last_error = exc
                continue

            if not results:
                continue

            tracks = list(getattr(results, "tracks", results))
            if not tracks:
                continue

            track = tracks[0]
            title = getattr(track, "title", None) or getattr(track, "identifier", "Unknown track")
            return QueueItem(track=track, title=str(title))

        if last_error is not None:
            raise RuntimeError(f"Search failed in Lavalink: {last_error}") from last_error
        raise RuntimeError("No results found for that query.")

    async def _send_status(self, guild_id: int, message: str) -> None:
        state = self._states.get(guild_id)
        if state is None or state.status_channel_id is None:
            return

        channel = self.bot.get_channel(state.status_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(state.status_channel_id)
            except Exception:
                return

        try:
            await channel.send(f"```{message}```")
        except Exception:
            return

    async def _play_next(self, guild_id: int, player: wavelink.Player) -> None:
        state = self._state(guild_id)

        async with state.lock:
            if player.playing or player.paused:
                return
            if not state.queue:
                state.current = None
                return
            item = state.queue.popleft()
            state.current = item

        try:
            await player.play(item.track)
        except Exception as exc:
            self._logger.warning("Failed to start track '%s': %s", item.title, exc)
            async with state.lock:
                state.current = None
            await self._send_status(guild_id, f"Track failed to start: {item.title}")
            await self._play_next(guild_id, player)

    async def _enqueue(self, member: discord.Member, query: str, status_channel_id: int | None = None) -> str:
        await self._ensure_node()
        player = await self._get_player(member)
        item = await self._search_track(query)
        state = self._state(member.guild.id)

        async with state.lock:
            state.status_channel_id = status_channel_id
            state.queue.append(item)
            queue_position = len(state.queue) + (1 if state.current else 0)

        if not player.playing and not player.paused:
            await self._play_next(member.guild.id, player)

        return f"Queued #{queue_position}: {item.title}"

    @commands.Cog.listener()
    async def on_ready(self):
        if self._node_ready:
            return
        try:
            await self._connect_lavalink()
            self._logger.info("Connected to Lavalink at %s", self.lavalink_uri)
        except Exception as exc:
            self._logger.warning("Failed to connect to Lavalink on startup: %s", exc)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player = payload.player
        if player is None or player.guild is None:
            return

        state = self._state(player.guild.id)
        async with state.lock:
            state.current = None

        await self._play_next(player.guild.id, player)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload):
        player = payload.player
        if player is None or player.guild is None:
            return

        self._logger.warning("Track exception on guild %s: %s", player.guild.id, payload.exception)
        state = self._state(player.guild.id)
        async with state.lock:
            state.current = None

        await self._send_status(
            player.guild.id,
            "Playback failed on this track due to YouTube source restrictions. Skipping to next item.",
        )
        await self._play_next(player.guild.id, player)

    @app_commands.command(name="play", description="Play a song from YouTube")
    @app_commands.describe(query="Song keywords or a YouTube URL")
    async def slash_play(self, interaction: discord.Interaction, query: str):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("This command can only run in a server.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            channel_id = interaction.channel.id if interaction.channel else None
            message = await self._enqueue(member, query, status_channel_id=channel_id)
            await interaction.followup.send(f"```{message}```")
        except Exception as exc:
            await interaction.followup.send(f"```{exc}```")

    @app_commands.command(name="p", description="Shortcut for /play")
    @app_commands.describe(query="Song keywords or a YouTube URL")
    async def slash_p(self, interaction: discord.Interaction, query: str):
        await self.slash_play(interaction, query)

    @commands.command(name="play", aliases=["p", "playing"], help="Play a selected song")
    async def play(self, ctx: commands.Context, *args: str):
        if not isinstance(ctx.author, discord.Member):
            await ctx.send("```This command can only run in a server.```")
            return

        query = " ".join(args).strip()
        if not query:
            await ctx.send("```Please provide a song name or URL.```")
            return

        try:
            message = await self._enqueue(ctx.author, query, status_channel_id=ctx.channel.id)
            await ctx.send(f"```{message}```")
        except Exception as exc:
            await ctx.send(f"```{exc}```")

    @commands.command(name="pause", help="Pause current song")
    async def pause(self, ctx: commands.Context):
        if ctx.guild is None:
            return
        player = ctx.guild.voice_client
        if not isinstance(player, wavelink.Player):
            await ctx.send("```Not connected to a Lavalink player.```")
            return

        if player.playing:
            await player.pause(True)
            await ctx.send("```Paused```")
            return

        if player.paused:
            await player.pause(False)
            await ctx.send("```Resumed```")
            return

        await ctx.send("```Nothing is playing right now.```")

    @commands.command(name="resume", aliases=["r"], help="Resume current song")
    async def resume(self, ctx: commands.Context):
        if ctx.guild is None:
            return
        player = ctx.guild.voice_client
        if not isinstance(player, wavelink.Player):
            await ctx.send("```Not connected to a Lavalink player.```")
            return

        if player.paused:
            await player.pause(False)
            await ctx.send("```Resumed```")
            return

        await ctx.send("```Nothing is paused right now.```")

    @commands.command(name="skip", aliases=["s"], help="Skip current song")
    async def skip(self, ctx: commands.Context):
        if ctx.guild is None:
            return
        player = ctx.guild.voice_client
        if not isinstance(player, wavelink.Player):
            await ctx.send("```Not connected to a Lavalink player.```")
            return

        if not player.playing and not player.paused:
            await ctx.send("```Nothing is playing right now.```")
            return

        await player.stop()
        await ctx.send("```Skipped```")

    @commands.command(name="queue", aliases=["q"], help="Display current queue")
    async def queue(self, ctx: commands.Context):
        if ctx.guild is None:
            return

        state = self._state(ctx.guild.id)
        lines: list[str] = []
        if state.current:
            lines.append(f"Now: {state.current.title}")
        if state.queue:
            for idx, item in enumerate(state.queue, start=1):
                lines.append(f"#{idx} {item.title}")

        if not lines:
            await ctx.send("```Queue is empty```")
            return

        await ctx.send("```" + "\n".join(lines) + "```")

    @commands.command(name="clear", aliases=["c", "bin"], help="Stop and clear queue")
    async def clear(self, ctx: commands.Context):
        if ctx.guild is None:
            return

        state = self._state(ctx.guild.id)
        async with state.lock:
            state.queue.clear()
            state.current = None

        player = ctx.guild.voice_client
        if isinstance(player, wavelink.Player) and (player.playing or player.paused):
            await player.stop()

        await ctx.send("```Queue cleared```")

    @commands.command(name="stop", aliases=["disconnect", "l", "d"], help="Disconnect from voice channel")
    async def stop(self, ctx: commands.Context):
        if ctx.guild is None:
            return

        state = self._state(ctx.guild.id)
        async with state.lock:
            state.queue.clear()
            state.current = None

        player = ctx.guild.voice_client
        if isinstance(player, wavelink.Player):
            await player.disconnect()

        await ctx.send("```Disconnected```")

    @commands.command(name="remove", help="Remove last queued song")
    async def remove(self, ctx: commands.Context):
        if ctx.guild is None:
            return

        state = self._state(ctx.guild.id)
        async with state.lock:
            if not state.queue:
                await ctx.send("```Queue is already empty```")
                return
            removed = state.queue.pop()

        await ctx.send(f"```Removed: {removed.title}```")
