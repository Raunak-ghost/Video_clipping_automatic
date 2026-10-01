"""Rename clips to human-readable names based on the source video title.

- Clips that are parts of one video (trigger_<vid>_highlight_N_...) become
  "<Video Title> - Part N.mp4".
- Single clips (trigger_<vid>_clip.mp4) become "<Video Title>.mp4".
- Video titles are fetched via yt-dlp (cached to title_cache.json).
- Updates clip_metadata.output_path + title and tasks.clip_path in the DB.
- Removes clip_metadata rows whose file no longer exists on disk.

Usage: python rename_clips.py
"""
import json
import re
import sqlite3
import time
from pathlib import Path

from yt_dlp import YoutubeDL

CLIPS_DIR = Path("clips")
DB = "video_clipping.db"
CACHE_FILE = Path("title_cache.json")

YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "skip_download": True,
    "cookiefile": "cookies.txt",
    "js_runtimes": {"node": {}},
    "extractor_args": {"youtube": {"player_client": ["web"]}},
}


def sanitize(name: str) -> str:
    # Remove Windows-invalid filename chars
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name[:120]  # keep paths reasonable


def fetch_title(video_id: str, cache: dict) -> str:
    if video_id in cache:
        return cache[video_id]
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
        title = info.get("title") or video_id
    except Exception as e:
        print(f"  !! title fetch failed for {video_id}: {e}")
        title = video_id
    cache[video_id] = title
    time.sleep(0.5)  # be gentle
    return title


def main():
    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    conn = sqlite3.connect(DB)

    files = sorted(CLIPS_DIR.rglob("*.mp4"))
    renamed = []
    used_names = set()

    for f in files:
        stem = f.stem
        m = re.match(r"trigger_([\w-]+?)(?:_highlight_(\d+))?_(?:clip|\d+_\d+)$", stem)
        if not m:
            # try simpler: trigger_<vid>_clip  or  trigger_<vid>_highlight_N_...
            m2 = re.match(r"trigger_([\w-]+)", stem)
            if not m2:
                continue  # run1/run2 etc - leave alone
            video_id = m2.group(1)
            part_m = re.search(r"highlight_(\d+)", stem)
            part = int(part_m.group(1)) if part_m else None
        else:
            video_id = m.group(1)
            part = int(m.group(2)) if m.group(2) else None

        title = sanitize(fetch_title(video_id, cache))
        new_stem = f"{title} - Part {part}" if part else title

        # avoid collisions
        candidate = new_stem
        n = 2
        while candidate.lower() in used_names or (f.parent / f"{candidate}.mp4").exists() and (f.parent / f"{candidate}.mp4") != f:
            candidate = f"{new_stem} ({n})"
            n += 1
        new_path = f.parent / f"{candidate}.mp4"

        if new_path == f:
            used_names.add(candidate.lower())
            continue

        old_rel = str(f)
        f.rename(new_path)
        used_names.add(candidate.lower())
        renamed.append((old_rel, str(new_path), candidate))

        # Update DB
        conn.execute("UPDATE clip_metadata SET output_path = ?, title = ? WHERE output_path = ?",
                     (str(new_path), candidate, old_rel))
        conn.execute("UPDATE tasks SET clip_path = ? WHERE clip_path = ?", (str(new_path), old_rel))

    # Clean stale DB rows pointing to files that no longer exist
    cur = conn.execute("SELECT id, output_path FROM clip_metadata")
    stale = [(r[0], r[1]) for r in cur.fetchall() if r[1] and not Path(r[1]).exists()]
    for row_id, path in stale:
        conn.execute("DELETE FROM clip_metadata WHERE id = ?", (row_id,))

    conn.commit()
    CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))

    print(f"\nRENAMED {len(renamed)}:")
    for old, new, _ in renamed:
        print(f"  {Path(old).name}  ->  {Path(new).name}")
    print(f"\nSTALE DB ROWS REMOVED: {len(stale)}")


if __name__ == "__main__":
    main()
