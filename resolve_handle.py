"""Resolve a YouTube @handle to its channel ID."""
import sys
from yt_dlp import YoutubeDL

for handle in sys.argv[1:]:
    url = f"https://www.youtube.com/{handle}"
    try:
        with YoutubeDL({"quiet": True, "extract_flat": True, "playlistend": 1,
                        "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        print(f"{handle} -> {info.get('channel_id')} ({info.get('channel') or info.get('uploader')})")
    except Exception as e:
        print(f"{handle} -> FAIL: {str(e)[:100]}")
