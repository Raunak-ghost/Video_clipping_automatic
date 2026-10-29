"""One-command runner for ComfyUI video generation across all evolved styles.

Usage:
    python generate_video.py "a giggling baby elephant in a pond"
    python generate_video.py --style anime "a lone cyberpunk samurai standing on a neon rooftop"
    python generate_video.py --style faceless "inside an ultra-modern automated robotics laboratory"
    python generate_video.py --style movie "a detective walking through rain at midnight"
    python generate_video.py --list-styles
    python generate_video.py --check
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------
# Environment Auto-Reexec into ComfyUI Venv
# --------------------------------------------------------------------------
COMFY_VENV_PYTHON = Path(r"D:\ComfyUI\venv\Scripts\python.exe")


def _ensure_venv():
    if os.environ.get("_COMFYUI_RUNNER_IN_VENV") == "1":
        return
    if COMFY_VENV_PYTHON.exists():
        try:
            current = os.path.normcase(str(Path(sys.executable).resolve()))
            target = os.path.normcase(str(COMFY_VENV_PYTHON.resolve()))
            if current != target:
                env = dict(os.environ, _COMFYUI_RUNNER_IN_VENV="1")
                rc = subprocess.call([str(COMFY_VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:], env=env)
                sys.exit(rc)
        except Exception as e:
            print(f"[WARN] Venv re-exec warning: {e}", file=sys.stderr)


_ensure_venv()

# --------------------------------------------------------------------------
# Main Execution (Guaranteed inside ComfyUI environment)
# --------------------------------------------------------------------------
from pipelines.generative.comfy_client import ComfyClient, SERVER_LOG
from pipelines.styles import get_style, list_styles, STYLE_REGISTRY


def main():
    parser = argparse.ArgumentParser(
        description="One-command ComfyUI video generation across all evolved styles.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prompt", nargs="?", default="", help="Prompt or visual theme for the video")
    parser.add_argument(
        "--style",
        default="kids",
        choices=list(STYLE_REGISTRY.keys()),
        help="Visual style to generate (maps to evolved editing_styles/*.md)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Sampling seed")
    parser.add_argument("--steps", type=int, default=20, help="Diffusion sampling steps (default: 20)")
    parser.add_argument("--cfg", type=float, default=5.0, help="Classifier-Free Guidance scale")
    parser.add_argument("--width", type=int, default=832, help="Video width (default: 832)")
    parser.add_argument("--height", type=int, default=480, help="Video height (default: 480)")
    parser.add_argument("--frames", type=int, default=81, help="Video frame count (81 ~= 3.5s at 24fps)")
    parser.add_argument("--fps", type=int, default=24, help="Frames per second")
    parser.add_argument("--list-styles", action="store_true", help="List all evolved styles and exit")
    parser.add_argument("--check", action="store_true", help="Run preflight server/model checks and exit")

    args = parser.parse_args()

    if args.list_styles:
        print("\nAvailable Evolved ComfyUI Styles (Preserving original editing_styles/*.md specs):")
        print("=" * 75)
        for name, spec in list_styles().items():
            print(f"  • {name:<26} -> Spec: {spec}")
        print("=" * 75)
        return 0

    client = ComfyClient()

    if args.check:
        print("[*] Running preflight check on ComfyUI environment...")
        ready = client.ensure_server(poll_timeout=60)
        if ready:
            print(f"[OK] ComfyUI server is healthy at {client.base_url}")
            return 0
        else:
            print(f"[FAIL] ComfyUI server failed to become ready. See {SERVER_LOG}", file=sys.stderr)
            return 1

    prompt_text = args.prompt.strip()
    if not prompt_text:
        # Default prompt if none provided
        prompt_text = "a cheerful baby elephant splashing happily in a pastel pond with a rubber duck"
        print(f"[*] No prompt provided. Using default: \"{prompt_text}\"")

    style_handler = get_style(args.style, client=client)
    print("=" * 70)
    print(f" ComfyUI Video Generation | Style: '{style_handler.name}'")
    print(f" Original Specification:   {getattr(style_handler, 'spec_file', 'n/a')}")
    print(f" Theme Prompt:             {prompt_text}")
    print("=" * 70)

    # 1. Ensure server is up
    if not client.ensure_server(poll_timeout=120):
        print(f"[FATAL] Server not available. Check {SERVER_LOG}", file=sys.stderr)
        return 1

    # 2. Build workflow graph
    workflow = style_handler.generate(
        prompt=prompt_text,
        seed=args.seed,
        steps=args.steps,
        cfg=args.cfg,
        width=args.width,
        height=args.height,
        frames=args.frames,
        fps=args.fps,
    )

    # 3. Submit prompt
    try:
        prompt_id = client.submit_prompt(workflow)
        print(f"[+] Submitted prompt ID: {prompt_id}")
    except Exception as e:
        print(f"[ERROR] Prompt submission failed: {e}", file=sys.stderr)
        return 1

    # 4. Poll execution
    try:
        entry, elapsed = client.poll_execution(prompt_id)
        out_path = client.extract_output_path(entry)
        print("\n" + "=" * 70)
        print(f" [SUCCESS] Video rendered in {int(elapsed // 60)}m {int(elapsed % 60)}s")
        if out_path:
            print(f" [OUTPUT]  {out_path}")
        print("=" * 70)
        return 0
    except KeyboardInterrupt:
        print("\n[!] Execution canceled by user.")
        return 130
    except Exception as e:
        print(f"\n[ERROR] Generation failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
