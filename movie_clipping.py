"""Movie Clipping Script - turn Hollywood movie files into recap clips.

Separate from the YouTube channel pipeline (trigger_engine/scheduler). This is
for actual produced films you have locally - drop a movie into the movies/
folder (or pass a path) and it generates 9:16 recap clips with the movie style
(full-screen footage + bold white center captions) plus paste-ready metadata.

Usage:
    python movie_clipping.py <movie_file> [--clips N] [--length SECONDS]
    python movie_clipping.py --all            # process every file in movies/

Examples:
    python movie_clipping.py movies/edward_scissorhands.mp4
    python movie_clipping.py "D:\\Movies\\Fight Club.mp4" --clips 10 --length 50
    python movie_clipping.py --all --clips 6

Output:
    clips/movie/<Movie Name>/<date>/<clip>.mp4
    upload_metadata/movie/<Movie Name>/<date>/<clip>.txt
"""
import argparse
import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from database import init_db, close
from pipeline import Pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("movie_clipping")

MOVIES_DIR = Path("movies")
CATEGORY = "movie"
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}


def get_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def movie_name_from(path: Path) -> str:
    """Clean a movie filename into a display name."""
    name = path.stem
    # strip common release-group junk: [1080p], (1990), .BluRay, -YTS, etc.
    import re
    name = re.sub(r"[\[\(].*?[\]\)]", "", name)
    name = re.sub(r"(?i)\b(1080p|720p|480p|2160p|4k|bluray|brrip|webrip|web-dl|"
                  r"x264|x265|hevc|aac|dts|yts|yify|extended|directors? cut)\b", "", name)
    name = re.sub(r"[._]+", " ", name).strip(" -")
    return name.strip() or path.stem


async def clip_movie(pipeline: Pipeline, movie_path: Path, clips: int, length: float) -> int:
    """Generate recap clips from one movie file. Returns number of clips made."""
    movie_name = movie_name_from(movie_path)
    dur = get_duration(movie_path)
    if dur < length + 20:
        logger.error(f"{movie_path.name}: too short ({dur:.0f}s) for {length}s clips")
        return 0

    logger.info(f"=== {movie_name} ({dur/60:.0f} min) -> {clips} clips of {length:.0f}s ===")

    # stagger clips across the film, skipping the opening credits and end credits
    usable = dur - length - 120  # skip ~2min end credits
    start_offset = 120.0          # skip ~2min opening
    step = max(60.0, (usable - start_offset) / clips)

    made = 0
    for i in range(clips):
        start = start_offset + i * step
        end = start + length
        if end > dur - 30:
            break
        task_id = f"movie_{movie_path.stem[:20]}_{int(start)}"
        title = f"{movie_name} part {i+1}"
        try:
            out = await pipeline._create_clip(
                str(movie_path), start, end, task_id, title, CATEGORY, movie_name
            )
            if out:
                made += 1
                logger.info(f"  [{made}/{clips}] {int(start)}-{int(end)}s -> {Path(out).name}")
        except Exception as e:
            logger.error(f"  clip {i+1} failed: {e}")

    return made


async def main() -> int:
    ap = argparse.ArgumentParser(description="Hollywood movie recap clipper")
    ap.add_argument("movie", nargs="?", help="path to a movie file")
    ap.add_argument("--all", action="store_true", help="process every file in movies/")
    ap.add_argument("--clips", type=int, default=8, help="clips per movie (default 8)")
    ap.add_argument("--length", type=float, default=45.0, help="clip length seconds (default 45)")
    args = ap.parse_args()

    # collect movie files
    movie_files = []
    if args.all:
        MOVIES_DIR.mkdir(exist_ok=True)
        movie_files = [f for f in sorted(MOVIES_DIR.iterdir()) if f.suffix.lower() in VIDEO_EXTS]
        if not movie_files:
            logger.error(f"no movie files in {MOVIES_DIR}/ - drop some .mp4/.mkv in there")
            return 2
    elif args.movie:
        p = Path(args.movie)
        if not p.exists():
            logger.error(f"file not found: {p}")
            return 2
        movie_files = [p]
    else:
        ap.print_help()
        return 2

    db = init_db()
    pipeline = Pipeline(db=db)
    total = 0
    for mf in movie_files:
        total += await clip_movie(pipeline, mf, args.clips, args.length)
    close(db)

    print(f"\nDONE: {total} movie recap clips from {len(movie_files)} movie(s)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
