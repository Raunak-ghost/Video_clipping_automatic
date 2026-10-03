"""Verify every channel in channels.txt resolves via yt-dlp."""
from yt_dlp import YoutubeDL

channels = []
for line in open("channels.txt", encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    parts = [p.strip() for p in line.split("|")]
    if len(parts) == 3:
        channels.append(parts)

for category, name, cid in channels:
    url = f"https://www.youtube.com/channel/{cid}/videos"
    try:
        with YoutubeDL({"quiet": True, "extract_flat": True, "playlistend": 1,
                        "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = info.get("entries") or []
        actual = info.get("channel") or info.get("uploader") or "?"
        print(f"OK    {name} ({cid}) -> channel: {actual}, entries: {len(entries)}")
    except Exception as e:
        print(f"FAIL  {name} ({cid}) -> {str(e)[:100]}")
