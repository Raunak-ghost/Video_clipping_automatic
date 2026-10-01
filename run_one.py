"""Retry tool: re-process a failed (or any) video through the pipeline, with DB updates.

Usage:
    python run_one.py <task_id> [video_url] [--category CAT] [--channel NAME]

- If video_url is omitted, it is taken from the task's DB record, or reconstructed
  from a 'trigger_<video_id>' task_id as a YouTube watch URL.
- The task is reset to 'pending' in the DB before re-processing, a retry is logged,
  and the final status/clip_path/error is written back by the pipeline itself.
- Bypasses Celery entirely (no 300s worker time limit).

Exit code: 0 = completed, 1 = failed, 2 = bad usage / task not found.
"""
import asyncio
import logging
import re
import sys

from database import Database, close
from pipeline import Pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_one")


def _resolve_video_url(db: Database, task_id: str) -> str | None:
    """Find the source URL for a task: DB record first, then trigger_<video_id> pattern."""
    task = db.get_task(task_id)
    if task and task.get("video_url"):
        return task["video_url"]
    m = re.match(r"trigger_([\w-]{6,})", task_id)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {a.split("=")[0][2:]: a.split("=")[1] for a in sys.argv[1:] if a.startswith("--") and "=" in a}

    if not args:
        print(__doc__)
        return 2

    task_id = args[0]
    video_url = args[1] if len(args) > 1 else None
    category = opts.get("category")
    channel = opts.get("channel")

    db = Database()
    try:
        existing = db.get_task(task_id)
        if not existing and not video_url:
            print(f"ERROR: task '{task_id}' not found in DB and no video_url given.")
            return 2

        if not video_url:
            video_url = _resolve_video_url(db, task_id)
        if not video_url:
            print(f"ERROR: could not resolve a video URL for task '{task_id}'. Pass it explicitly.")
            return 2

        # Reset / create the task and log the retry
        if not existing:
            db.create_task(task_id)
        previous_status = existing.get("status", "?") if existing else "new"
        db.update_task_status(task_id, "pending", progress=0.0, video_url=video_url)
        task_row = db.get_task(task_id)
        db.log_message(
            task_row["id"],
            "INFO",
            f"Manual retry via run_one.py (previous status: {previous_status})",
        )
        logger.info("Retrying task %s -> %s (previous status: %s)", task_id, video_url, previous_status)

        pipeline = Pipeline(db=db)
        result = asyncio.run(
            pipeline.process_video(video_url, task_id=task_id, category=category, channel_name=channel)
        )

        status = result.get("status")
        db.log_message(
            task_row["id"],
            "INFO" if status == "completed" else "ERROR",
            f"Retry finished: {status}" + (f" - {result.get('error')}" if result.get("error") else ""),
        )
        print("RESULT:", result)
        return 0 if status == "completed" else 1
    finally:
        close(db)


if __name__ == "__main__":
    sys.exit(main())
