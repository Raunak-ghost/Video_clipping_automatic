"""Master CLI for Video Production Studio.

Provides a unified single entrypoint for clipping, AI video generation,
batch processing, hardware inspection, and server hosting.

Commands:
    python run.py generate "prompt" [--style anime|kids|faceless|movie|hormozi]
    python run.py clip <url_or_path> [--task-id ID] [--category CAT] [--channel NAME]
    python run.py movie <movie_path> [--clips N] [--length SECONDS]
    python run.py batch [--clips-per-video N] [--target-total M]
    python run.py resubtitle
    python run.py serve [--port 8001]
    python run.py copyright <check|add|check-all> [args...]
    python run.py hardware
"""

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

# Auto-reexec into local .venv if run with global python, unless running generate
LOCAL_VENV_PYTHON = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"


def _auto_reexec():
    if os.environ.get("_RUN_PY_IN_VENV") == "1":
        return
    # If subcommand is 'generate', generate_video.py handles its own reexec to ComfyUI venv
    if len(sys.argv) > 1 and sys.argv[1] == "generate":
        return
    if LOCAL_VENV_PYTHON.exists() and sys.prefix == sys.base_prefix:
        env = dict(os.environ, _RUN_PY_IN_VENV="1")
        rc = subprocess.call([str(LOCAL_VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:], env=env)
        sys.exit(rc)


_auto_reexec()


COMFY_VENV_PYTHON = Path(r"D:\ComfyUI\venv\Scripts\python.exe")


def cmd_hardware(args):
    from core.hardware import print_hardware_summary
    print_hardware_summary()


def cmd_generate(args):
    """Delegate to generate_video.py inside ComfyUI environment."""
    py_exec = str(COMFY_VENV_PYTHON) if COMFY_VENV_PYTHON.exists() else sys.executable
    cmd = [py_exec, "generate_video.py"] + sys.argv[2:]
    return subprocess.call(cmd)


def cmd_clip(args):
    from core.database import Database, close
    from pipelines.clipping import ClipperPipeline as Pipeline

    video_url = args.target
    task_id = args.task_id or f"clip_{int(sys.time() if hasattr(sys, 'time') else 1000)}"
    import time
    task_id = args.task_id or f"manual_{int(time.time())}"

    print(f"[*] Processing clip: {video_url} (task: {task_id})")
    db = Database()
    try:
        pipeline = Pipeline(db=db)
        result = asyncio.run(
            pipeline.process_video(
                video_url=video_url,
                task_id=task_id,
                category=args.category,
                channel_name=args.channel,
            )
        )
        print("\n" + "=" * 65)
        print(f" Pipeline Status: {result.get('status')}")
        if result.get("clips"):
            for i, c in enumerate(result["clips"], 1):
                print(f"   Clip [{i}]: {c}")
        if result.get("error"):
            print(f"   Error:    {result['error']}")
        print("=" * 65)
        return 0 if result.get("status") == "completed" else 1
    finally:
        close(db)


def cmd_movie(args):
    from movie_clipping import main as run_movie
    sys.argv = ["movie_clipping.py"] + args.movie_args
    return asyncio.run(run_movie())


def cmd_batch(args):
    from batch_clips import main as run_batch
    sys.argv = ["batch_clips.py"] + args.batch_args
    return asyncio.run(run_batch())


def cmd_resubtitle(args):
    from resubtitle_clips import main as run_resub
    return asyncio.run(run_resub())


def cmd_serve(args):
    from main import main as run_main
    run_main()


def cmd_copyright(args):
    from copyright_check import main as run_copyright
    sys.argv = ["copyright_check.py"] + args.cr_args
    return run_copyright()


def main():
    parser = argparse.ArgumentParser(
        prog="python run.py",
        description="Unified Video Production Studio CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # 1. hardware
    subparsers.add_parser("hardware", help="Inspect GPUs & FFmpeg hardware acceleration")

    # 2. generate (ComfyUI)
    p_gen = subparsers.add_parser("generate", help="Generate AI video via ComfyUI (WAN 2.2)")
    p_gen.add_argument("extra_args", nargs=argparse.REMAINDER, help="Arguments passed to generate_video.py")

    # 3. clip (Pipeline processing)
    p_clip = subparsers.add_parser("clip", help="Download, analyze with Ollama & clip a video")
    p_clip.add_argument("target", help="YouTube URL or local video path")
    p_clip.add_argument("--task-id", help="Optional task ID")
    p_clip.add_argument("--category", help="Video niche/category (e.g. tech_news, anime, movie, podcasts)")
    p_clip.add_argument("--channel", help="Channel name attribution")

    # 4. movie
    p_mov = subparsers.add_parser("movie", help="Cut recap clips from a local movie file")
    p_mov.add_argument("movie_args", nargs=argparse.REMAINDER, help="Arguments passed to movie_clipping.py")

    # 5. batch
    p_bat = subparsers.add_parser("batch", help="Batch-process clips from downloads/")
    p_bat.add_argument("batch_args", nargs=argparse.REMAINDER, help="Arguments passed to batch_clips.py")

    # 6. resubtitle
    subparsers.add_parser("resubtitle", help="Re-render all clips in clips/ with word-by-word subtitles")

    # 7. serve
    subparsers.add_parser("serve", help="Start FastAPI Webhook/Studio UI & APScheduler")

    # 8. copyright
    p_cr = subparsers.add_parser("copyright", help="Perceptual hash & Content ID copyright checker")
    p_cr.add_argument("cr_args", nargs=argparse.REMAINDER, help="Arguments passed to copyright_check.py")

    args, unknown = parser.parse_known_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "hardware": cmd_hardware,
        "generate": cmd_generate,
        "clip": cmd_clip,
        "movie": cmd_movie,
        "batch": cmd_batch,
        "resubtitle": cmd_resubtitle,
        "serve": cmd_serve,
        "copyright": cmd_copyright,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args) or 0
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
