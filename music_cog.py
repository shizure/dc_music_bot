import discord
from discord import app_commands
from discord.ext import commands
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
import asyncio
import base64
import json
import logging
import os
import re
import time
from pathlib import Path
import shutil
import uuid
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

class music_cog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._logger = logging.getLogger(__name__)
    
        # all the music related stuff
        self.is_playing = False
        self.is_paused = False

        # 2d array containing [song, channel]
        self.music_queue = []
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        self.youtube_search_mode = os.getenv("YOUTUBE_SEARCH_MODE", "fallback").strip().lower()
        self.youtube_url_metadata_api = os.getenv("YOUTUBE_API_LOOKUP_URLS", "0").strip().lower() in ('1', 'true', 'yes', 'on')
        self.use_cookie_file = os.getenv("YTDLP_USE_COOKIES", "0").strip().lower() in ('1', 'true', 'yes', 'on')
        self.prefer_opus_copy = os.getenv("FFMPEG_PREFER_COPY", "0").strip().lower() in ('1', 'true', 'yes', 'on')
        self.pre_download_audio = os.getenv("YTDLP_PRE_DOWNLOAD", "1").strip().lower() in ('1', 'true', 'yes', 'on')
        raw_clients = os.getenv("YTDLP_PLAYER_CLIENTS", "web,mweb,android")
        self.player_clients = [client.strip() for client in raw_clients.split(',') if client.strip()]
        if not self.player_clients:
            self.player_clients = ['web', 'mweb', 'android']
        self.autocomplete_enabled = os.getenv("YOUTUBE_AUTOCOMPLETE_ENABLED", "1").strip().lower() in ('1', 'true', 'yes', 'on')
        self.autocomplete_min_chars = self._read_int_env("YOUTUBE_AUTOCOMPLETE_MIN_CHARS", 4)
        self.autocomplete_max_results = max(1, min(self._read_int_env("YOUTUBE_AUTOCOMPLETE_MAX_RESULTS", 5), 10))
        self.autocomplete_cooldown_seconds = self._read_int_env("YOUTUBE_AUTOCOMPLETE_COOLDOWN_SECONDS", 8)
        self.ytdlp_rate_limit_cooldown_seconds = self._read_int_env("YTDLP_429_COOLDOWN_SECONDS", 240)
        self._yt_cache_ttl_seconds = self._read_int_env("YOUTUBE_API_CACHE_TTL_SECONDS", 21600)
        self._yt_cache_max_entries = self._read_int_env("YOUTUBE_API_CACHE_MAX_ENTRIES", 256)
        self._yt_cache = {}
        self._last_autocomplete_fetch_at = 0.0
        self._ytdlp_blocked_until = 0.0

        self._cookie_file_path = self._write_cookie_file_from_env()
        self.YDL_OPTIONS = self._build_ydl_options(format_selector='bestaudio/best')
        self.FFMPEG_OPTIONS_STREAM = {
            'before_options': '-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn -loglevel warning',
        }
        self.FFMPEG_OPTIONS_LOCAL = {
            'before_options': '-nostdin',
            'options': '-vn -loglevel warning',
        }
        requested_binary = os.getenv("FFMPEG_PATH", "ffmpeg")
        self.ffmpeg_executable = requested_binary
        if shutil.which(requested_binary) is None and imageio_ffmpeg is not None:
            # Fall back to bundled static ffmpeg when host image lacks system ffmpeg.
            self.ffmpeg_executable = imageio_ffmpeg.get_ffmpeg_exe()

        self.vc = None
        self.status_channel = None
        self._current_temp_file = None
        self._temp_audio_dir = Path('/tmp/dc_music_bot_audio')
        self._temp_audio_dir.mkdir(parents=True, exist_ok=True)

    def _read_int_env(self, name: str, default: int) -> int:
        raw = os.getenv(name)
        if not raw:
            return default
        try:
            value = int(raw)
            return value if value > 0 else default
        except ValueError:
            return default

    def _cache_get(self, key: str):
        entry = self._yt_cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            self._yt_cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key: str, value):
        while len(self._yt_cache) >= self._yt_cache_max_entries:
            oldest = next(iter(self._yt_cache), None)
            if oldest is None:
                break
            self._yt_cache.pop(oldest, None)
        self._yt_cache[key] = (time.time() + self._yt_cache_ttl_seconds, value)

    def _is_rate_limited_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return 'http error 429' in text or 'too many requests' in text

    def _mark_ytdlp_blocked(self):
        self._ytdlp_blocked_until = time.time() + self.ytdlp_rate_limit_cooldown_seconds

    def _ensure_ytdlp_available(self):
        if time.time() < self._ytdlp_blocked_until:
            remaining = int(self._ytdlp_blocked_until - time.time())
            raise RuntimeError(f'YouTube is rate-limiting this host. Try again in about {remaining} seconds.')

    def _friendly_playback_error(self, exc: Exception) -> str:
        text = str(exc).lower()
        if self._is_rate_limited_error(exc):
            return 'YouTube is rate-limiting this host right now. Please try again in a few minutes.'
        if 'requested format is not available' in text or 'only images are available' in text:
            return 'YouTube blocked playable formats for this request on the current host. Try another track later.'
        if 'drm protected' in text:
            return 'This video is DRM protected and cannot be played by the bot.'
        return 'Could not get a playable stream URL from YouTube. Try another track.'

    def _get_cached_autocomplete_results(self, normalized_query: str) -> list[dict]:
        for size in range(len(normalized_query), self.autocomplete_min_chars - 1, -1):
            key = f"search:api:many:{normalized_query[:size]}:{self.autocomplete_max_results}"
            cached = self._cache_get(key)
            if not cached:
                continue
            filtered = [item for item in cached if normalized_query in item['title'].lower()]
            if filtered:
                return filtered[:self.autocomplete_max_results]
            return cached[:self.autocomplete_max_results]
        return []

    def _extract_video_id(self, value: str) -> str | None:
        try:
            parsed = urlparse(value.strip())
        except Exception:
            return None

        host = parsed.netloc.lower()
        if host.startswith('www.'):
            host = host[4:]

        if host == 'youtu.be':
            video_id = parsed.path.strip('/').split('/')[0]
            return video_id or None

        if host in ('youtube.com', 'm.youtube.com', 'music.youtube.com'):
            if parsed.path == '/watch':
                query = parse_qs(parsed.query)
                vid = query.get('v', [None])[0]
                return vid

            match = re.match(r'^/(shorts|embed|live)/([^/?#]+)', parsed.path)
            if match:
                return match.group(2)

        return None

    def _youtube_api_get(self, endpoint: str, params: dict) -> dict:
        if not self.youtube_api_key:
            raise RuntimeError('YOUTUBE_API_KEY is not configured')
        request_params = dict(params)
        request_params['key'] = self.youtube_api_key
        url = f"https://www.googleapis.com/youtube/v3/{endpoint}?{urlencode(request_params)}"
        req = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'dc-music-bot/1.0'})

        try:
            with urlopen(req, timeout=8) as response:
                raw = response.read().decode('utf-8')
        except HTTPError as exc:
            raise RuntimeError(f'YouTube API HTTP error: {exc.code}') from exc
        except URLError as exc:
            raise RuntimeError(f'YouTube API network error: {exc.reason}') from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError('YouTube API returned invalid JSON') from exc

        if payload.get('error'):
            message = payload['error'].get('message', 'Unknown YouTube API error')
            raise RuntimeError(message)
        return payload

    def _search_with_youtube_api(self, query: str) -> dict:
        cache_key = f"search:api:{query.strip().lower()}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        payload = self._youtube_api_get(
            endpoint='search',
            params={
                'part': 'snippet',
                'type': 'video',
                'maxResults': 1,
                'q': query,
                'videoEmbeddable': 'true',
                'videoSyndicated': 'true',
                'fields': 'items(id/videoId,snippet/title,snippet/liveBroadcastContent)',
            },
        )

        items = payload.get('items') or []
        if not items:
            raise RuntimeError('No search results returned by YouTube API')

        first = items[0]
        video_id = (first.get('id') or {}).get('videoId')
        if not video_id:
            raise RuntimeError('Search result did not include a video ID')

        snippet = first.get('snippet') or {}
        if snippet.get('liveBroadcastContent') in ('live', 'upcoming'):
            raise RuntimeError('Top result is a live stream; try a different query')

        result = {
            'source': f'https://www.youtube.com/watch?v={video_id}',
            'title': unescape(snippet.get('title') or 'Search result'),
        }
        self._cache_set(cache_key, result)
        return result

    def _search_many_with_youtube_api(self, query: str, max_results: int = 10) -> list[dict]:
        normalized = query.strip().lower()
        if not normalized:
            return []

        max_results = max(1, min(max_results, 10))
        cache_key = f"search:api:many:{normalized}:{max_results}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        payload = self._youtube_api_get(
            endpoint='search',
            params={
                'part': 'snippet',
                'type': 'video',
                'maxResults': max_results,
                'q': query,
                'videoEmbeddable': 'true',
                'videoSyndicated': 'true',
                'fields': 'items(id/videoId,snippet/title,snippet/liveBroadcastContent)',
            },
        )

        results = []
        for item in payload.get('items') or []:
            snippet = item.get('snippet') or {}
            if snippet.get('liveBroadcastContent') in ('live', 'upcoming'):
                continue
            video_id = (item.get('id') or {}).get('videoId')
            if not video_id:
                continue
            title = unescape(snippet.get('title') or 'Search result')
            results.append({'title': title, 'source': f'https://www.youtube.com/watch?v={video_id}'})

        self._cache_set(cache_key, results)
        if results:
            self._cache_set(f"search:api:{normalized}", results[0])
        return results

    def _get_video_metadata_with_api(self, video_id: str) -> dict | None:
        cache_key = f"video:api:{video_id}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        payload = self._youtube_api_get(
            endpoint='videos',
            params={
                'part': 'snippet',
                'id': video_id,
                'maxResults': 1,
                'fields': 'items(id,snippet/title,snippet/liveBroadcastContent)',
            },
        )
        items = payload.get('items') or []
        if not items:
            return None

        snippet = items[0].get('snippet') or {}
        data = {
            'title': unescape(snippet.get('title') or 'Requested URL'),
            'is_live': snippet.get('liveBroadcastContent') in ('live', 'upcoming'),
        }
        self._cache_set(cache_key, data)
        return data

    def _search_keywords(self, query: str) -> dict:
        cache_key = f"search:any:{query.strip().lower()}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        mode = self.youtube_search_mode
        if mode not in ('fallback', 'api', 'ytdlp'):
            mode = 'fallback'

        if mode == 'ytdlp' or not self.youtube_api_key:
            result = self._search_with_ytdlp(query)
            self._cache_set(cache_key, result)
            return result

        if mode == 'api':
            try:
                result = self._search_with_youtube_api(query)
            except Exception as api_error:
                self._logger.warning('YouTube API search failed; falling back to yt-dlp: %s', api_error)
                result = self._search_with_ytdlp(query)
            self._cache_set(cache_key, result)
            return result

        try:
            result = self._search_with_ytdlp(query)
            self._cache_set(cache_key, result)
            return result
        except Exception as ytdlp_error:
            self._logger.warning('yt-dlp search failed; falling back to YouTube API: %s', ytdlp_error)
            result = self._search_with_youtube_api(query)
            self._cache_set(cache_key, result)
            return result

    def _build_ydl_options(
        self,
        format_selector: str | None,
        extract_flat: bool = False,
        player_clients: list[str] | None = None,
        use_cookies: bool = True,
    ) -> dict:
        youtube_args = {}
        if player_clients:
            youtube_args['player_client'] = player_clients

        # Optional yt-dlp anti-bot inputs from environment variables.
        # Example values:
        # YTDLP_MWEB_PO_TOKEN="mweb.gvs+XXX"
        # YTDLP_WEB_PO_TOKEN="web.gvs+XXX"
        # YTDLP_DATA_SYNC_ID="XXX"
        mweb_po_token = os.getenv('YTDLP_MWEB_PO_TOKEN')
        web_po_token = os.getenv('YTDLP_WEB_PO_TOKEN')
        data_sync_id = os.getenv('YTDLP_DATA_SYNC_ID')
        po_tokens = []
        if mweb_po_token:
            po_tokens.append(mweb_po_token)
        if web_po_token:
            po_tokens.append(web_po_token)
        if po_tokens:
            youtube_args['po_token'] = po_tokens
        if data_sync_id:
            youtube_args['data_sync_id'] = [data_sync_id]

        options = {
            'noplaylist': True,
            'js_runtimes': {'node': {}},
        }
        if youtube_args:
            options['extractor_args'] = {'youtube': youtube_args}
        if format_selector:
            options['format'] = format_selector
        if extract_flat:
            options['extract_flat'] = 'in_playlist'
            options['skip_download'] = True
            options['quiet'] = True
        if use_cookies and self.use_cookie_file and self._cookie_file_path:
            options['cookiefile'] = self._cookie_file_path
        return options

    def _write_cookie_file_from_env(self) -> str | None:
        cookie_path = os.getenv("YTDLP_COOKIE_FILE")
        if cookie_path:
            p = Path(cookie_path)
            if p.exists():
                self._logger.info('Using yt-dlp cookie file: %s', p)
                return str(p)
            self._logger.warning('YTDLP_COOKIE_FILE not found: %s', p)

        raw_b64 = os.getenv("YTDLP_COOKIES_B64")
        if not raw_b64:
            return None

        try:
            cookie_text = base64.b64decode(raw_b64).decode("utf-8")
            cookie_file = Path("/tmp/youtube_cookies.txt")
            cookie_file.write_text(cookie_text, encoding="utf-8")
            self._logger.info('Wrote yt-dlp cookies from YTDLP_COOKIES_B64 to /tmp/youtube_cookies.txt')
            return str(cookie_file)
        except Exception as exc:
            self._logger.warning('Failed to decode YTDLP_COOKIES_B64: %s', exc)
            return None

    def _search_with_ytdlp(self, query: str) -> dict:
        self._ensure_ytdlp_available()
        info = None
        errors = []
        cookie_attempts = [True, False] if self._cookie_file_path else [False]
        if not self.use_cookie_file:
            cookie_attempts = [False]

        for use_cookies in cookie_attempts:
            try:
                search_ydl = YoutubeDL(self._build_ydl_options(format_selector=None, extract_flat=True, use_cookies=use_cookies))
                info = search_ydl.extract_info(f"ytsearch1:{query}", download=False)
                break
            except Exception as exc:
                if self._is_rate_limited_error(exc):
                    self._mark_ytdlp_blocked()
                errors.append(f"cookies={use_cookies}: {exc}")
                continue

        if info is None:
            raise RuntimeError("; ".join(errors) or "No search results returned by yt-dlp")

        entries = info.get("entries") or []
        if not entries:
            raise RuntimeError("No search results returned by yt-dlp")
        first = entries[0]
        url = first.get("webpage_url") or first.get("url")
        if url and url.startswith("/watch"):
            url = f"https://www.youtube.com{url}"
        if not url and first.get("id"):
            url = f"https://www.youtube.com/watch?v={first['id']}"
        title = first.get("title") or "Search result"
        if not url:
            raise RuntimeError("Search result did not include a URL")
        return {'source': url, 'title': unescape(title)}

    def _extract_audio_stream_url(self, source_url: str) -> str:
        self._ensure_ytdlp_available()
        attempts = [
            (None, self.player_clients),
        ]

        info = None
        last_error = None
        cookie_attempts = [True, False] if self._cookie_file_path else [False]
        if not self.use_cookie_file:
            cookie_attempts = [False]

        for use_cookies in cookie_attempts:
            for fmt, clients in attempts:
                try:
                    ydl = YoutubeDL(self._build_ydl_options(format_selector=fmt, player_clients=clients, use_cookies=use_cookies))
                    info = ydl.extract_info(source_url, download=False)
                    break
                except DownloadError as exc:
                    last_error = exc
                    if self._is_rate_limited_error(exc):
                        self._mark_ytdlp_blocked()
                    self._logger.warning(
                        'yt-dlp extraction attempt failed (format=%s clients=%s cookies=%s): %s',
                        fmt,
                        clients,
                        use_cookies,
                        exc,
                    )
                    continue
            if info is not None:
                break

        if info is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError('yt-dlp failed to extract media info for this URL.')

        formats = info.get('formats') or []
        audio_only = []
        audio_with_video = []
        for fmt in formats:
            if not fmt.get('url'):
                continue
            if fmt.get('acodec') in (None, 'none'):
                continue
            if fmt.get('has_drm'):
                continue

            protocol = (fmt.get('protocol') or '').lower()
            ext = (fmt.get('ext') or '').lower()
            if protocol in ('mhtml',) or ext in ('mhtml',):
                continue
            if 'm3u8' in protocol or 'dash' in protocol:
                continue

            if fmt.get('vcodec') in (None, 'none'):
                audio_only.append(fmt)
            else:
                audio_with_video.append(fmt)

        def _score(f: dict) -> tuple:
            abr = f.get('abr') or 0
            tbr = f.get('tbr') or 0
            preference = f.get('preference') or 0
            return (preference, abr, tbr)

        if audio_only:
            best = max(audio_only, key=_score)
            return best['url']

        if audio_with_video:
            best = max(audio_with_video, key=_score)
            return best['url']

        direct = info.get('url')
        if direct:
            return direct

        raise RuntimeError('Could not find a playable audio stream URL from yt-dlp result.')

    def _download_audio_file(self, source_url: str) -> str:
        self._ensure_ytdlp_available()
        cookie_attempts = [True, False] if self._cookie_file_path else [False]
        if not self.use_cookie_file:
            cookie_attempts = [False]

        last_error = None
        for use_cookies in cookie_attempts:
            try:
                output_template = self._temp_audio_dir / f"%(id)s-{uuid.uuid4().hex}.%(ext)s"
                options = self._build_ydl_options(
                    format_selector='bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio',
                    player_clients=self.player_clients,
                    use_cookies=use_cookies,
                )
                options.update(
                    {
                        'outtmpl': str(output_template),
                        'quiet': True,
                        'noprogress': True,
                        'retries': 2,
                        'socket_timeout': 10,
                    }
                )
                ydl = YoutubeDL(options)
                info = ydl.extract_info(source_url, download=True)

                requested = info.get('requested_downloads') or []
                if requested:
                    filepath = requested[0].get('filepath')
                    if filepath and Path(filepath).exists():
                        return filepath

                fallback_path = ydl.prepare_filename(info)
                if fallback_path and Path(fallback_path).exists():
                    return fallback_path

                base = info.get('id')
                if base:
                    matches = sorted(self._temp_audio_dir.glob(f"{base}-*.*"), key=lambda p: p.stat().st_mtime, reverse=True)
                    if matches:
                        return str(matches[0])

                raise RuntimeError('yt-dlp download completed but file path was not found')
            except Exception as exc:
                last_error = exc
                if self._is_rate_limited_error(exc):
                    self._mark_ytdlp_blocked()
                self._logger.warning('yt-dlp pre-download failed (cookies=%s): %s', use_cookies, exc)

        if last_error:
            raise last_error
        raise RuntimeError('yt-dlp pre-download failed')

    def _resolve_playback_input(self, source_url: str) -> dict:
        if self.pre_download_audio:
            try:
                local_path = self._download_audio_file(source_url)
                return {'input': local_path, 'temp_file': local_path}
            except Exception as exc:
                self._logger.warning('Pre-download failed, falling back to stream URL: %s', exc)

        stream_url = self._extract_audio_stream_url(source_url)
        return {'input': stream_url, 'temp_file': None}

    def _cleanup_temp_file(self):
        temp_file = self._current_temp_file
        self._current_temp_file = None
        if not temp_file:
            return
        try:
            Path(temp_file).unlink(missing_ok=True)
        except Exception as exc:
            self._logger.warning('Failed to remove temp audio file %s: %s', temp_file, exc)

    def _after_play(self, error):
        if error is not None:
            self._logger.warning('Playback error: %s', error)
            asyncio.run_coroutine_threadsafe(
                self._notify_status_channel("Playback failed while streaming audio. Try another track."),
                self.bot.loop,
            )
        self._cleanup_temp_file()
        asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

    async def _notify_status_channel(self, message: str):
        if self.status_channel is None:
            return
        try:
            await self.status_channel.send(f"```{message}```")
        except Exception as exc:
            self._logger.warning('Failed to send status message: %s', exc)

    def _build_audio_source(self, playback_input: str):
        is_remote = playback_input.startswith(('http://', 'https://'))
        ffmpeg_options = self.FFMPEG_OPTIONS_STREAM if is_remote else self.FFMPEG_OPTIONS_LOCAL
        if self.prefer_opus_copy:
            try:
                return discord.FFmpegOpusAudio(
                    playback_input,
                    executable=self.ffmpeg_executable,
                    codec='copy',
                    **ffmpeg_options,
                )
            except Exception as exc:
                self._logger.warning('FFmpegOpusAudio codec=copy failed, falling back to libopus: %s', exc)

        return discord.FFmpegOpusAudio(
            playback_input,
            executable=self.ffmpeg_executable,
            codec='libopus',
            **ffmpeg_options,
        )

    # searching the item on youtube
    def search_yt(self, item):
        item = item.strip()
        if item.startswith(('https://', 'http://')):
            video_id = self._extract_video_id(item)
            canonical_url = f'https://www.youtube.com/watch?v={video_id}' if video_id else item

            if self.youtube_api_key and self.youtube_url_metadata_api and video_id:
                try:
                    metadata = self._get_video_metadata_with_api(video_id)
                    if metadata and metadata.get('is_live'):
                        raise RuntimeError('Live streams are not supported in this bot')
                    if metadata:
                        return {'source': canonical_url, 'title': metadata['title']}
                except Exception as exc:
                    self._logger.warning('YouTube API metadata lookup failed for %s: %s', video_id, exc)

            return {'source': canonical_url, 'title': 'Requested URL'}

        return self._search_keywords(item)

    async def play_next(self):
        if len(self.music_queue) > 0:
            self.is_playing = True

            #get the first url
            m_url = self.music_queue[0][0]['source']

            #remove the first element as you are currently playing it
            self.music_queue.pop(0)
            loop = asyncio.get_event_loop()
            try:
                resolved = await loop.run_in_executor(None, lambda: self._resolve_playback_input(m_url))
            except Exception as exc:
                self._logger.warning('Stream extraction failed in play_next: %s', exc)
                self.is_playing = False
                return
            self._cleanup_temp_file()
            self._current_temp_file = resolved.get('temp_file')
            source = self._build_audio_source(resolved['input'])
            try:
                self.vc.play(source, after=self._after_play)
            except Exception:
                self._cleanup_temp_file()
                raise
        else:
            self.is_playing = False

    # infinite loop checking 
    async def play_music(self, send_message):
        if len(self.music_queue) > 0:
            self.is_playing = True

            m_url = self.music_queue[0][0]['source']
            #try to connect to voice channel if you are not already connected
            if self.vc == None or not self.vc.is_connected():
                self.vc = await self.music_queue[0][1].connect()

                #in case we fail to connect
                if self.vc == None:
                    await send_message("```Could not connect to the voice channel```")
                    return
            else:
                await self.vc.move_to(self.music_queue[0][1])
            #remove the first element as you are currently playing it
            self.music_queue.pop(0)
            loop = asyncio.get_event_loop()
            try:
                resolved = await loop.run_in_executor(None, lambda: self._resolve_playback_input(m_url))
            except DownloadError as exc:
                self._logger.warning('YouTube extraction blocked: %s', exc)
                await send_message(f"```{self._friendly_playback_error(exc)}```")
                self.is_playing = False
                return
            except Exception as exc:
                self._logger.warning('Stream extraction failed: %s', exc)
                await send_message(f"```{self._friendly_playback_error(exc)}```")
                self.is_playing = False
                return

            try:
                self._cleanup_temp_file()
                self._current_temp_file = resolved.get('temp_file')
                source = self._build_audio_source(resolved['input'])
                self.vc.play(source, after=self._after_play)
            except Exception as exc:
                self._cleanup_temp_file()
                self._logger.warning('Failed to start FFmpeg playback: %s', exc)
                await send_message("```Playback process could not start. Try another track.```")
                self.is_playing = False
                return

        else:
            self.is_playing = False

    async def _enqueue_request(self, query: str, voice_channel, send_message, status_channel=None):
        loop = asyncio.get_running_loop()
        self.status_channel = status_channel
        if self.is_paused:
            if self.vc:
                self.vc.resume()
            self.is_paused = False
            self.is_playing = True
            await send_message("```Resumed playback```")
            return

        try:
            song = await loop.run_in_executor(None, lambda: self.search_yt(query))
        except DownloadError as exc:
            self._logger.warning('YouTube metadata blocked: %s', exc)
            await send_message("```YouTube blocked metadata lookup for this URL. Try another video or use keywords instead.```")
            return
        except Exception as exc:
            self._logger.warning('Search failed: %s', exc)
            await send_message("```Could not process that query. Try another link or keywords.```")
            return

        if self.is_playing:
            await send_message(f"**#{len(self.music_queue)+2} -'{song['title']}'** added to the queue")
        else:
            await send_message(f"**'{song['title']}'** added to the queue")
        self.music_queue.append([song, voice_channel])
        if self.is_playing == False:
            await self.play_music(send_message)

    async def _handle_slash_play(self, interaction: discord.Interaction, query: str):
        member = interaction.user
        voice_state = getattr(member, 'voice', None)
        voice_channel = getattr(voice_state, 'channel', None)
        if voice_channel is None:
            await interaction.response.send_message("You need to join a voice channel first.", ephemeral=True)
            return

        query = query.strip()
        if not query:
            await interaction.response.send_message("Please provide a song name or URL.", ephemeral=True)
            return

        await interaction.response.defer()
        await self._enqueue_request(query, voice_channel, interaction.followup.send, interaction.channel)

    async def _autocomplete_choices(self, current: str):
        query = current.strip()
        if not self.autocomplete_enabled or len(query) < self.autocomplete_min_chars or not self.youtube_api_key:
            return []

        normalized = query.lower()
        cached = self._get_cached_autocomplete_results(normalized)
        now = time.time()
        if cached and (now - self._last_autocomplete_fetch_at) < self.autocomplete_cooldown_seconds:
            suggestions = cached
        else:
            loop = asyncio.get_running_loop()
            try:
                suggestions = await loop.run_in_executor(None, lambda: self._search_many_with_youtube_api(query, max_results=self.autocomplete_max_results))
                self._last_autocomplete_fetch_at = now
            except Exception as exc:
                self._logger.warning('Autocomplete lookup failed: %s', exc)
                suggestions = cached

        if not suggestions:
            return []

        choices = []
        for item in suggestions[:self.autocomplete_max_results]:
            label = item['title']
            if len(label) > 100:
                label = f"{label[:97]}..."
            choices.append(app_commands.Choice(name=label, value=item['source']))
        return choices

    @app_commands.command(name="play", description="Play a song from YouTube")
    @app_commands.describe(query="Song keywords or a YouTube URL")
    async def slash_play(self, interaction: discord.Interaction, query: str):
        await self._handle_slash_play(interaction, query)

    @slash_play.autocomplete('query')
    async def slash_play_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._autocomplete_choices(current)

    @app_commands.command(name="p", description="Shortcut for /play")
    @app_commands.describe(query="Song keywords or a YouTube URL")
    async def slash_p(self, interaction: discord.Interaction, query: str):
        await self._handle_slash_play(interaction, query)

    @slash_p.autocomplete('query')
    async def slash_p_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._autocomplete_choices(current)

    @commands.command(name="play", aliases=["p","playing"], help="Plays a selected song from youtube")
    async def play(self, ctx, *args):
        query = " ".join(args)
        if not query.strip():
            await ctx.send("```Please provide a song name or URL```")
            return
        try:
            voice_channel = ctx.author.voice.channel
        except Exception:
            await ctx.send("```You need to connect to a voice channel first!```")
            return
        await self._enqueue_request(query, voice_channel, ctx.send, ctx.channel)

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
            await self.play_music(ctx.send)


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
        self._cleanup_temp_file()
        if self.vc and self.vc.is_connected():
            await self.vc.disconnect()
    
    @commands.command(name="remove", help="Removes last song added to queue")
    async def re(self, ctx):
        if not self.music_queue:
            await ctx.send("```Queue is already empty```")
            return
        self.music_queue.pop()
        await ctx.send("```last song removed```")
