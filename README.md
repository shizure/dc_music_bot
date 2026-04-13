# dc_music_bot (Lavalink Edition)

This bot now uses Lavalink for audio playback.

That means:
- no local yt-dlp extraction in Python
- no local FFmpeg process in Python bot code
- no local Opus loading in Python bot code

## What You Deploy

You need 2 services:
1. Bot service (this repository)
2. Lavalink service (separate service)

## Bot Environment Variables

Required:
- `TOKEN` (or `DISCORD_TOKEN`)
- `LAVALINK_URI` (example: `http://lavalink:2333`)
- `LAVALINK_PASSWORD`

Optional:
- `DISCORD_GUILD_ID` for instant slash command sync in one server
- `BOT_PREFIX` (default `?`)
- `LAVALINK_SEARCH_PREFIX` (default `ytmsearch`)

## Railway Setup (Simple)

1. Keep this repository as your bot service.
2. Create a second Railway service from the same repository using Dockerfile path: `lavalink.Dockerfile`.
3. Configure Lavalink with a password.
	Edit `lavalink.application.yml.example` and set `lavalink.server.password`.
4. Set bot vars:
- `LAVALINK_URI` to your Lavalink internal URL
- `LAVALINK_PASSWORD` to the same Lavalink password
5. Deploy both services.

## Important Note About YouTube

For Lavalink v4, YouTube playback works best with the `youtube-source` plugin enabled on Lavalink.
The plugin should:
- disable built-in youtube source (`lavalink.server.sources.youtube: false`)
- enable plugin search (`plugins.youtube.allowSearch: true`)
- configure clients (example: `MUSIC`, `ANDROID_VR`, `WEB`, `WEBEMBEDDED`)

If Lavalink is running but YouTube queries return no tracks, the issue is usually Lavalink plugin/source config, not your Python bot.

If playback fails with `All clients failed to load the item`, redeploy Lavalink so updated `plugins.youtube.clients` order is applied.

## Kept Project Files

- `main.py`
- `music_cog.py`
- `help_cog.py`
- `requirements.txt`
- `nixpacks.toml`
