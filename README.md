# dc_music_bot

## Railway deploy notes

This repo includes [nixpacks.toml](nixpacks.toml), so Railway installs FFmpeg automatically.

Required variable:
- TOKEN

After deploy/redeploy, verify FFmpeg in Railway logs:
- Look for: "FFmpeg detected at: ..."

Optional manual check in Railway shell:
- ffmpeg -version

If FFmpeg is not found, set:
- FFMPEG_PATH=ffmpeg

