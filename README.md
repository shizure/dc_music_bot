# dc_music_bot

## Railway deploy notes

This repo includes [nixpacks.toml](nixpacks.toml), so Railway installs FFmpeg automatically.

Required variable:
- TOKEN

Optional YouTube Data API v3 variables:
- YOUTUBE_API_KEY: YouTube Data API v3 key
- YOUTUBE_SEARCH_MODE: search strategy (`fallback`, `api`, `ytdlp`), default is `fallback`
- YOUTUBE_API_CACHE_TTL_SECONDS: in-memory cache TTL in seconds, default `21600` (6 hours)
- YOUTUBE_API_CACHE_MAX_ENTRIES: in-memory cache size, default `256`
- YOUTUBE_API_LOOKUP_URLS: set `1` to call API for direct URL title lookup, default `0`

How quota is protected by default:
- Mode `fallback` tries `yt-dlp` search first (0 API quota), then uses API only when yt-dlp search fails.
- Search results are cached in-memory to avoid repeated identical API calls.
- Direct YouTube URLs do not consume API quota unless `YOUTUBE_API_LOOKUP_URLS=1`.

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

