"""Re-render all existing clips with the 'subtitles' edit style
(centered word-by-word captions). Originals are replaced in place on success,
so DB paths and the admin panel keep working unchanged.

Usage: python resubtitle_clips.py
"""
import asyncio
import logging
import subprocess
from pathlib import Path

from database import Database, close
from pipeline import Pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("resubtitle")


def get_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip() or 0)


async def main() -> None:
    db = Database()
    pipeline = Pipeline(db=db)

    clips = [
        p for p in sorted(Path("clips").rglob("*.mp4"))
        if not p.stem.endswith("_tmp")
    ]
    logger.info("Found %d clips to re-render with subtitles", len(clips))

    ok = fail = 0
    for i, clip in enumerate(clips, 1):
        tmp = clip.with_name(clip.stem + "_tmp.mp4")
        try:
            duration = get_duration(clip)
            if duration <= 0:
                raise ValueError("zero duration")
            logger.info("[%d/%d] %s (%.1fs)", i, len(clips), clip, duration)
            await pipeline.edit_video_clip(
                video_path=str(clip),
                clip_start=0.0,
                clip_end=duration,
                output_path=str(tmp),
                style="subtitles",
                task_id=f"resub_{clip.stem}",
            )
            tmp.replace(clip)
            # Remove the sidecar .ass if it was left next to the tmp file
            ass = tmp.with_suffix(".ass")
            if ass.exists():
                ass.unlink()
            ok += 1
            logger.info("  OK -> %s", clip)
        except Exception as e:
            fail += 1
            logger.error("  FAILED %s: %s", clip, e)
            if tmp.exists():
                tmp.unlink()

    close(db)
    print(f"\nDONE: {ok} re-rendered, {fail} failed out of {len(clips)}")


if __name__ == "__main__":
    asyncio.run(main())
