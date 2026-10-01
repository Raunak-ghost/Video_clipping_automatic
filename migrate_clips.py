"""One-time migration: move existing clips into clips/<category>/<channel>/<YYYY-MM-DD>/.

- Resolves trigger_<video_id> clips to their channel via yt-dlp (cached).
- Maps channel_id -> (category, channel name) from channels.txt.
- Date folder comes from the file's modification time.
- Duplicate copies (same filename + size, e.g. youtube/tiktok/instagram folders)
  are consolidated: first copy is moved, later identical copies are deleted.
- Updates clip_metadata.output_path in the DB.
"""
import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from yt_dlp import YoutubeDL

CLIPS_DIR = Path("clips")
DB = "video_clipping.db"
CHANNELS_FILE = "channels.txt"
CACHE_FILE = Path("migrate_channel_cache.json")

# Known prefixes for hand-named run files
PREFIX_MAP = {
    "mkbhd": ("tech_news", "Marques Brownlee"),
    "huberman": ("podcasts", "Huberman Lab"),
    "doac": ("podcasts", "Diary of a CEO"),
}


def load_channels():
    mapping = {}  # channel_id -> (category, name)
    for line in Path(CHANNELS_FILE).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3:
            category, name, channel_id = parts
            mapping[channel_id] = (category, name)
    return mapping


def sanitize(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in (" ", "_", "-", ".")).strip()


def resolve_channel(video_id: str, cache: dict) -> str:
    """Return channel_id for a YouTube video id (cached)."""
    if video_id in cache:
        return cache[video_id]
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with YoutubeDL({"quiet": True, "noplaylist": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            cid = info.get("channel_id") or ""
    except Exception as e:
        print(f"  !! could not resolve {video_id}: {e}")
        cid = ""
    cache[video_id] = cid
    return cid


def main():
    channels = load_channels()
    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}

    conn = sqlite3.connect(DB)
    moved, deleted, skipped = [], [], []

    # Collect all mp4s under clips/ (root + platform folders)
    files = sorted(CLIPS_DIR.rglob("*.mp4"), key=lambda f: len(f.parts))  # root first
    seen_dest = {}  # (filename, size) -> dest path

    for f in files:
        # Skip files already in the new structure (clips/<cat>/<channel>/<date>/...)
        rel = f.relative_to(CLIPS_DIR)
        if len(rel.parts) >= 4:
            skipped.append((str(rel), "already organized"))
            continue

        stem = f.stem
        category = channel = None

        m = re.match(r"trigger_([\w-]+)", stem)
        if m:
            video_id = m.group(1)
            cid = resolve_channel(video_id, cache)
            if cid and cid in channels:
                category, channel = channels[cid]
        else:
            for prefix, (cat, chan) in PREFIX_MAP.items():
                if stem.lower().startswith(prefix):
                    category, channel = cat, chan
                    break

        if not category:
            category, channel = "uncategorized", "unknown_channel"

        date_str = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
        dest_dir = CLIPS_DIR / sanitize(category) / sanitize(channel) / date_str
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f.name

        key = (f.name, f.stat().st_size)
        if key in seen_dest and seen_dest[key].exists():
            # Identical duplicate already moved -> delete this copy
            f.unlink()
            deleted.append(str(rel))
            continue

        if dest.exists() and dest.stat().st_size == f.stat().st_size:
            f.unlink()
            deleted.append(str(rel))
            continue

        shutil.move(str(f), str(dest))
        seen_dest[key] = dest
        moved.append((str(rel), str(dest.relative_to(CLIPS_DIR))))

        # Update DB paths pointing at the old location
        old_rel = str(Path("clips") / rel)
        conn.execute(
            "UPDATE clip_metadata SET output_path = ? WHERE output_path = ?",
            (str(dest), old_rel),
        )
        conn.execute(
            "UPDATE tasks SET clip_path = ? WHERE clip_path = ?",
            (str(dest), old_rel),
        )

    conn.commit()
    CACHE_FILE.write_text(json.dumps(cache, indent=2))

    # Remove now-empty platform folders
    for d in sorted(CLIPS_DIR.iterdir()):
        if d.is_dir() and d.name in ("youtube", "tiktok", "instagram"):
            if not any(d.iterdir()):
                d.rmdir()
                print(f"removed empty folder: {d}")

    print(f"\nMOVED {len(moved)}:")
    for old, new in moved:
        print(f"  {old}  ->  {new}")
    print(f"\nDUPLICATES DELETED {len(deleted)}:")
    for d in deleted:
        print(f"  {d}")
    print(f"\nSKIPPED {len(skipped)}:")
    for s, why in skipped:
        print(f"  {s} ({why})")


if __name__ == "__main__":
    main()
