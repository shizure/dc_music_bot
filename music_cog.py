import discord
from discord.ext import commands
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
import asyncio
import base64
import os
from pathlib import Path
import shutil

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

class music_cog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
        #all the music related stuff
        self.is_playing = False
        self.is_paused = False

        # 2d array containing [song, channel]
        self.music_queue = []
        self._cookie_file_path = self._write_cookie_file_from_env()
        self.YDL_OPTIONS = {
            'format': 'bestaudio/best',
            'js_runtimes': {'node': {}},
            'noplaylist': True,
        }
        if self._cookie_file_path:
            self.YDL_OPTIONS['cookiefile'] = self._cookie_file_path
        self.FFMPEG_OPTIONS = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn',
        }
        requested_binary = os.getenv("FFMPEG_PATH", "ffmpeg")
        self.ffmpeg_executable = requested_binary
        if shutil.which(requested_binary) is None and imageio_ffmpeg is not None:
            # Fall back to bundled static ffmpeg when host image lacks system ffmpeg.
            self.ffmpeg_executable = imageio_ffmpeg.get_ffmpeg_exe()

        self.vc = None
        try:
            self.ytdl = YoutubeDL(self.YDL_OPTIONS)
        except ValueError:
            # Keep startup resilient if yt-dlp changes option schema.
            self.ytdl = YoutubeDL({'format': 'bestaudio/best'})

    def _write_cookie_file_from_env(self) -> str | None:
        cookie_path = os.getenv("YTDLP_COOKIE_FILE")
        if cookie_path:
            p = Path(cookie_path)
            if p.exists():
                print(f"Using yt-dlp cookie file: {p}")
                return str(p)
            print(f"YTDLP_COOKIE_FILE not found: {p}")

        raw_b64 = os.getenv("YTDLP_COOKIES_B64")
        if not raw_b64:
            return None

        try:
            cookie_text = base64.b64decode(raw_b64).decode("utf-8")
            cookie_file = Path("/tmp/youtube_cookies.txt")
            cookie_file.write_text(cookie_text, encoding="utf-8")
            print("Wrote yt-dlp cookies from YTDLP_COOKIES_B64 to /tmp/youtube_cookies.txt")
            return str(cookie_file)
        except Exception as exc:
            print(f"Failed to decode YTDLP_COOKIES_B64: {exc}")
            return None

    def _search_with_ytdlp(self, query: str) -> dict:
        info = self.ytdl.extract_info(f"ytsearch1:{query}", download=False)
        entries = info.get("entries") or []
        if not entries:
            raise RuntimeError("No search results returned by yt-dlp")
        first = entries[0]
        url = first.get("webpage_url") or first.get("url")
        title = first.get("title") or "Search result"
        if not url:
            raise RuntimeError("Search result did not include a URL")
        return {'source': url, 'title': title}

    def _extract_audio_stream_url(self, source_url: str) -> str:
        info = self.ytdl.extract_info(source_url, download=False)
        direct = info.get('url')
        if direct:
            return direct

        formats = info.get('formats') or []
        for fmt in reversed(formats):
            if fmt.get('acodec') in (None, 'none'):
                continue
            stream_url = fmt.get('url')
            if stream_url:
                return stream_url

        raise RuntimeError('Could not find a playable audio stream URL from yt-dlp result.')

    def _after_play(self, error):
        if error is not None:
            print(f"Playback error: {error}")
        asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

     #searching the item on youtube
    def search_yt(self, item):
        if item.startswith("https://"):
            # Avoid a heavy metadata request here; extraction is handled right before playback.
            return {'source': item, 'title': 'Requested URL'}
        return self._search_with_ytdlp(item)

    async def play_next(self):
        if len(self.music_queue) > 0:
            self.is_playing = True

            #get the first url
            m_url = self.music_queue[0][0]['source']

            #remove the first element as you are currently playing it
            self.music_queue.pop(0)
            loop = asyncio.get_event_loop()
            try:
                song = await loop.run_in_executor(None, lambda: self._extract_audio_stream_url(m_url))
            except Exception as exc:
                print(f"Stream extraction failed in play_next: {exc}")
                self.is_playing = False
                return
            self.vc.play(
                discord.FFmpegOpusAudio(song, executable=self.ffmpeg_executable, **self.FFMPEG_OPTIONS),
                after=self._after_play,
            )
        else:
            self.is_playing = False

    # infinite loop checking 
    async def play_music(self, ctx):
        print(f"play_music called. queue length: {len(self.music_queue)}, is_playing: {self.is_playing}")
        if len(self.music_queue) > 0:
            self.is_playing = True

            m_url = self.music_queue[0][0]['source']
            #try to connect to voice channel if you are not already connected
            if self.vc == None or not self.vc.is_connected():
                print(f"Attempting to connect to: {self.music_queue[0][1]}")
                self.vc = await self.music_queue[0][1].connect()
                print(f"Connected: {self.vc}")

                #in case we fail to connect
                if self.vc == None:
                    await ctx.send("```Could not connect to the voice channel```")
                    return
            else:
                await self.vc.move_to(self.music_queue[0][1])
            #remove the first element as you are currently playing it
            self.music_queue.pop(0)
            loop = asyncio.get_event_loop()
            try:
                song = await loop.run_in_executor(None, lambda: self._extract_audio_stream_url(m_url))
            except DownloadError as exc:
                print(f"YouTube extraction blocked: {exc}")
                await ctx.send("```YouTube blocked this request (bot-check/cookies required). Try another video or use search keywords.```")
                self.is_playing = False
                return
            except Exception as exc:
                print(f"Stream extraction failed: {exc}")
                await ctx.send("```Could not get a playable stream URL from YouTube. Try another track.```")
                self.is_playing = False
                return

            print(f"Starting playback via: {song[:120]}")
            self.vc.play(
                discord.FFmpegOpusAudio(song, executable=self.ffmpeg_executable, **self.FFMPEG_OPTIONS),
                after=self._after_play,
            )

        else:
            self.is_playing = False

    @commands.command(name="play", aliases=["p","playing"], help="Plays a selected song from youtube")
    async def play(self, ctx, *args):
        query = " ".join(args)
        try:
            voice_channel = ctx.author.voice.channel
        except:
            await ctx.send("```You need to connect to a voice channel first!```")
            return
        if self.is_paused:
            self.vc.resume()
        else:
            try:
                song = self.search_yt(query)
            except DownloadError as exc:
                print(f"YouTube metadata blocked: {exc}")
                await ctx.send("```YouTube blocked metadata lookup for this URL. Try another video or use keywords instead.```")
                return
            except Exception as exc:
                print(f"Search failed: {exc}")
                await ctx.send("```Could not process that query. Try another link or keywords.```")
                return
            if type(song) == type(True):
                await ctx.send("```Could not download the song. Incorrect format try another keyword. This could be due to playlist or a livestream format.```")
            else:
                if self.is_playing:
                    await ctx.send(f"**#{len(self.music_queue)+2} -'{song['title']}'** added to the queue")  
                else:
                    await ctx.send(f"**'{song['title']}'** added to the queue")  
                self.music_queue.append([song, voice_channel])
                if self.is_playing == False:
                    await self.play_music(ctx)

    @commands.command(name="pause", help="Pauses the current song being played")
    async def pause(self, ctx, *args):
        if self.is_playing:
            self.is_playing = False
            self.is_paused = True
            self.vc.pause()
        elif self.is_paused:
            self.is_paused = False
            self.is_playing = True
            self.vc.resume()

    @commands.command(name = "resume", aliases=["r"], help="Resumes playing with the discord bot")
    async def resume(self, ctx, *args):
        if self.is_paused:
            self.is_paused = False
            self.is_playing = True
            self.vc.resume()

    @commands.command(name="skip", aliases=["s"], help="Skips the current song being played")
    async def skip(self, ctx):
        if self.vc != None and self.vc:
            self.vc.stop()
            #try to play next in the queue if it exists
            await self.play_music(ctx)


    @commands.command(name="queue", aliases=["q"], help="Displays the current songs in queue")
    async def queue(self, ctx):
        retval = ""
        for i in range(0, len(self.music_queue)):
            retval += f"#{i+1} -" + self.music_queue[i][0]['title'] + "\n"

        if retval != "":
            await ctx.send(f"```queue:\n{retval}```")
        else:
            await ctx.send("```No music in queue```")

    @commands.command(name="clear", aliases=["c", "bin"], help="Stops the music and clears the queue")
    async def clear(self, ctx):
        if self.vc != None and self.is_playing:
            self.vc.stop()
        self.music_queue = []
        await ctx.send("```Music queue cleared```")

    @commands.command(name="stop", aliases=["disconnect", "l", "d"], help="Kick the bot from VC")
    async def dc(self, ctx):
        self.is_playing = False
        self.is_paused = False
        await self.vc.disconnect()
    
    @commands.command(name="remove", help="Removes last song added to queue")
    async def re(self, ctx):
        self.music_queue.pop()
        await ctx.send("```last song removed```")
