# Deployment Notes

## Important limitation with Vercel and Discord bots

Vercel runs Python as serverless functions. Discord bots need a long-lived websocket connection,
which cannot stay alive in a serverless request/response lifecycle.

This means:
- The dashboard UI can be deployed on Vercel.
- The Discord bot process itself should run on a persistent host (Railway, Render, Fly.io, VPS).

If you click Start on Vercel, the API now returns a clear message explaining this limitation.

## Vercel environment variable setup

If your dashboard/API on Vercel still needs token-aware checks, add one of these env vars:
- `TOKEN`
- `DISCORD_TOKEN`

If your bot host should use YouTube Data API v3 search fallback, also set:
- `YOUTUBE_API_KEY`
- Optional `YOUTUBE_SEARCH_MODE` (`fallback`, `api`, `ytdlp`), default `fallback`
- Optional `YOUTUBE_API_CACHE_TTL_SECONDS` (default `21600`)
- Optional `YOUTUBE_API_CACHE_MAX_ENTRIES` (default `256`)
- Optional `YOUTUBE_API_LOOKUP_URLS` (default `0` to avoid URL metadata API quota use)
- Optional `YTDLP_USE_COOKIES` (set `0` if your `YTDLP_COOKIES_B64` export is stale)
- Optional `FFMPEG_PREFER_COPY` (default `0`; keep `0` for stability)

In Vercel:
1. Open your project.
2. Go to Settings > Environment Variables.
3. Add key `TOKEN` with your Discord bot token value (and optional YouTube variables above).
4. Select Production (and Preview/Development if needed).
5. Redeploy the project so the new variable is applied.

You can verify by opening the deployment and checking Runtime Logs for startup messages.

## Recommended architecture

1. Deploy this dashboard where your bot process runs, OR
2. Keep dashboard on Vercel and point it to an API on your persistent bot host.

This repository's control panel entrypoint is `control_panel.py` and Vercel routes through `api/index.py`.

## Local run

```bash
set TOKEN=your_discord_bot_token
python control_panel.py
```

Open http://localhost:5000
