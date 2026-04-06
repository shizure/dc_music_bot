# dc_music_bot

## Railway deploy notes

This repo includes [nixpacks.toml](nixpacks.toml), so Railway installs FFmpeg automatically.

Required variable:
- TOKEN

Optional variables for YouTube anti-bot pages:
- YTDLP_COOKIE_FILE: absolute path to a cookies.txt file in Netscape format
- YTDLP_COOKIES_B64: base64-encoded contents of cookies.txt (the app writes it to /tmp)

After deploy/redeploy, verify FFmpeg in Railway logs:
- Look for: "FFmpeg detected at: ..."

Optional manual check in Railway shell:
- ffmpeg -version

If FFmpeg is not found, set:
- FFMPEG_PATH=ffmpeg

