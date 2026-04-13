# dc_music_bot

## Railway deploy notes

This repo includes [nixpacks.toml](nixpacks.toml), so Railway installs FFmpeg automatically.

Required variable:
- TOKEN

Optional Discord command sync variable:
- DISCORD_GUILD_ID: sync slash commands instantly to a specific server for faster testing

Optional YouTube Data API v3 variables:
- YOUTUBE_API_KEY: YouTube Data API v3 key
- YOUTUBE_SEARCH_MODE: search strategy (`fallback`, `api`, `ytdlp`), default is `fallback` (recommended for low quota usage)
- YOUTUBE_API_CACHE_TTL_SECONDS: in-memory cache TTL in seconds, default `21600` (6 hours)
- YOUTUBE_API_CACHE_MAX_ENTRIES: in-memory cache size, default `256`
- YOUTUBE_API_LOOKUP_URLS: set `1` to call API for direct URL title lookup, default `0`
- YOUTUBE_AUTOCOMPLETE_ENABLED: enable slash autocomplete API suggestions, default `1`
- YOUTUBE_AUTOCOMPLETE_MIN_CHARS: minimum query length before API autocomplete, default `4`
- YOUTUBE_AUTOCOMPLETE_MAX_RESULTS: max slash autocomplete suggestions, default `5`
- YOUTUBE_AUTOCOMPLETE_COOLDOWN_SECONDS: cooldown between autocomplete API fetches, default `8`
- YTDLP_USE_COOKIES: set `1` to use cookie file for yt-dlp requests, default `0`
- YTDLP_PLAYER_CLIENTS: comma-separated yt-dlp clients for extraction, default `web,mweb,android`
- YTDLP_PRE_DOWNLOAD: set `1` to download audio to temp file before playback for stability, default `1`
- YTDLP_429_COOLDOWN_SECONDS: block repeated yt-dlp attempts after HTTP 429, default `240`
- FFMPEG_PREFER_COPY: set `1` only if you explicitly want codec copy mode, default `0`

How quota is protected by default:
- Mode `fallback` tries `yt-dlp` search first (0 API quota), then uses API only when yt-dlp search fails.
- Search results are cached in-memory to avoid repeated identical API calls.
- Direct YouTube URLs do not consume API quota unless `YOUTUBE_API_LOOKUP_URLS=1`.
- Slash autocomplete now uses minimum-length + cooldown + cache to reduce API calls.

Slash command support:
- `/play <query>` and `/p <query>` are available.
- As you type query text, autocomplete returns up to 10 YouTube API suggestions.
- For immediate command visibility while testing, set `DISCORD_GUILD_ID`.

Optional variables for YouTube anti-bot pages:
- YTDLP_COOKIE_FILE: absolute path to a cookies.txt file in Netscape format
- YTDLP_COOKIES_B64: base64-encoded contents of cookies.txt (the app writes it to /tmp)
- YTDLP_MWEB_PO_TOKEN: optional mweb PO token, example `mweb.gvs+XXX`
- YTDLP_WEB_PO_TOKEN: optional web PO token, example `web.gvs+XXX`
- YTDLP_DATA_SYNC_ID: optional YouTube Data Sync ID

After deploy/redeploy, verify FFmpeg in Railway logs:
- Look for: "FFmpeg detected at: ..."

Optional manual check in Railway shell:
- ffmpeg -version

If FFmpeg is not found, set:
- FFMPEG_PATH=ffmpeg

