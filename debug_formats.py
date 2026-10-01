"""Debug: list available formats for a video across player clients."""
import sys
from yt_dlp import YoutubeDL

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=1_iNTFSw4Nc"
clients = sys.argv[2].split(",") if len(sys.argv) > 2 else ["android", "ios", "mweb", "tv"]

for client in clients:
    print(f"\n=== player_client: {client} ===")
    opts = {
        "quiet": True, "noplaylist": True, "skip_download": True,
        "cookiefile": "cookies.txt",
        "extractor_args": {"youtube": {"player_client": [client]}},
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        fmts = info.get("formats") or []
        print(f"{len(fmts)} formats:")
        for f in fmts[:15]:
            print(f"  {f.get('format_id')}: {f.get('ext')} {f.get('resolution')} "
                  f"vcodec={f.get('vcodec')} acodec={f.get('acodec')}")
    except Exception as e:
        print(f"  ERROR: {e}")
