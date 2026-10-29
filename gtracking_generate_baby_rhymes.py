#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gtracking_generate_baby_rhymes.py
===================================
One-click, fully self-contained generator for 3D-animated baby-rhymes videos.

No PowerShell needed - just click Run (or `python gtracking_generate_baby_rhymes.py`).
The script handles every step itself:

  1. Re-launches itself under the ComfyUI venv interpreter (D:\\ComfyUI\\venv) if needed.
  2. Verifies the WAN 2.2 TI2V-5B model files exist (downloads any missing ones).
  3. Starts the local ComfyUI server (http://127.0.0.1:8188) if it is not already up.
  4. Writes a story for each theme using a local LLM via Ollama (llama3.1:8b by
     default, deterministic template fallback if Ollama is unavailable).
  5. Builds the WAN 2.2 text-to-video workflow and submits it to ComfyUI.
  6. Polls queue/history with a live progress bar (expect ~1.5-2.5 h per video
     on an AMD RX 7900 XTX).
  7. Probes the rendered MP4 (duration / codec / resolution / fps) and writes a
     detailed markdown report of every processing step, error and result.

Examples:
    python gtracking_generate_baby_rhymes.py "a giggling baby elephant splashing in a bubbly pond"
    python gtracking_generate_baby_rhymes.py --list themes.txt --seed 7
    python gtracking_generate_baby_rhymes.py --check        # preflight only, no generation
"""

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------
# Fixed configuration (this machine)
# --------------------------------------------------------------------------
VENV_PYTHON = Path(r"D:\ComfyUI\venv\Scripts\python.exe")
COMFYUI_ROOT = Path(r"D:\ComfyUI\ComfyUI")
COMFYUI_MAIN = COMFYUI_ROOT / "main.py"
COMFYUI_URL = "http://127.0.0.1:8188"
SERVER_LOG = Path(r"D:\ComfyUI\comfyui_server.log")
OUTPUT_DIR = COMFYUI_ROOT / "output"
OLLAMA_URL = "http://localhost:11434"
CLIENT_ID = "gtracking-baby-rhymes"

# (filename, models subdir, download url, minimum size in MB)
MODELS = [
    ("wan2.2_ti2v_5B_fp16.safetensors", "diffusion_models",
     "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_repackaged/resolve/main/"
     "split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors", 9000),
    ("umt5_xxl_fp8_e4m3fn_scaled.safetensors", "text_encoders",
     "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/"
     "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", 6000),
    ("wan2.2_vae.safetensors", "vae",
     "https://huggingface.co/Comfy-Org/Wan-2.2/resolve/main/"
     "split_files/vae/wan2.2_vae.safetensors", 1200),
]

NEGATIVE_PROMPT = ("blurry, low quality, distorted, deformed, extra limbs, watermark, "
                   "text, subtitles, flickering, static, dark, scary")
STYLE_SUFFIX = ("ultra detailed, high quality animation, vibrant candy colors, warm golden "
                "lighting, smooth gentle camera motion, adorable characters with big "
                "sparkling eyes")

STORY_SYSTEM = (
    "You write visual scene descriptions for a text-to-video AI model that renders "
    "3D-animated baby-rhyme videos for toddlers. Given a theme, write ONE continuous "
    "scene (90-140 words, present tense): describe the cute characters, the colorful "
    "setting, the playful action, the lighting and the gentle camera motion. Concrete "
    "visual language only. No dialogue, no lyrics, no scene cuts, no transitions, no "
    "camera directions beyond a single smooth motion. Reply with the scene description only."
)

DEFAULT_THEMES = [
    "a giggling baby elephant splashing in a bubbly pastel pond with a rubber duck",
]

DEFAULT_REPORT = Path(__file__).resolve().parent / "gtracking_generate_report.md"


# --------------------------------------------------------------------------
# Step 0: make sure we run inside the ComfyUI venv (stdlib only until here)
# --------------------------------------------------------------------------
def _running_in_venv() -> bool:
    try:
        me = os.path.normcase(str(Path(sys.executable).resolve()))
        target = os.path.normcase(str(VENV_PYTHON.resolve()))
        return me == target
    except OSError:
        return False


def _reexec_into_venv() -> None:
    if _running_in_venv() or os.environ.get("_GTRACKING_IN_VENV") == "1":
        return
    if not VENV_PYTHON.exists():
        sys.exit("[FATAL] ComfyUI venv python not found: %s" % VENV_PYTHON)
    print("[venv] re-launching under ComfyUI venv: %s" % VENV_PYTHON, flush=True)
    env = dict(os.environ, _GTRACKING_IN_VENV="1")
    rc = subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:], env=env)
    sys.exit(rc)


_reexec_into_venv()

# Third-party imports - guaranteed available inside the venv.
import requests  # noqa: E402
from requests.adapters import HTTPAdapter  # noqa: E402
from urllib3.util.retry import Retry  # noqa: E402
from tqdm import tqdm  # noqa: E402

http_session = requests.Session()
_retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
_adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=_retries)
http_session.mount('http://', _adapter)
http_session.mount('https://', _adapter)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


def human_time(seconds) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dh %02dm %02ds" % (h, m, s)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


def md_cell(x) -> str:
    return str(x if x is not None else "").replace("|", "/").replace("\n", " ").strip()


def step(name, detail, status="ok"):
    return {"time": hms(), "step": name, "detail": detail, "status": status}


# --------------------------------------------------------------------------
# Step 1: model files
# --------------------------------------------------------------------------
def download_model(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(tmp, "wb") as f, tqdm(total=total, unit="B", unit_scale=True,
                                        desc=dest.name, dynamic_ncols=True) as bar:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))
    tmp.rename(dest)


def ensure_models():
    """Verify required WAN 2.2 model files; download any that are missing."""
    results, all_ok = [], True
    for filename, subdir, url, min_mb in MODELS:
        path = COMFYUI_ROOT / "models" / subdir / filename
        if path.exists() and path.stat().st_size >= min_mb * 1024 * 1024:
            detail = "present (%.1f MB)" % (path.stat().st_size / (1024 ** 2))
            print("[models] %s - %s" % (filename, detail), flush=True)
            results.append(step("model " + filename, detail))
            continue
        print("[models] %s missing - downloading ..." % filename, flush=True)
        try:
            download_model(url, path)
            detail = "downloaded (%.1f MB)" % (path.stat().st_size / (1024 ** 2))
            results.append(step("model " + filename, detail))
        except Exception as e:
            all_ok = False
            results.append(step("model " + filename, "FAILED: %s" % e, "error"))
    return results, all_ok


# --------------------------------------------------------------------------
# Step 2: ComfyUI server
# --------------------------------------------------------------------------
def server_healthy(timeout: float = 5.0) -> bool:
    try:
        r = http_session.get(COMFYUI_URL + "/system_stats", timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def ensure_server(poll_timeout: int = 300):
    """Return (detail, ok). Start the ComfyUI server if it is not already up."""
    if server_healthy():
        print("[server] ComfyUI already running at %s" % COMFYUI_URL, flush=True)
        return "already running at %s" % COMFYUI_URL, True
    if not COMFYUI_MAIN.exists():
        return "entrypoint not found: %s" % COMFYUI_MAIN, False
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with open(SERVER_LOG, "ab") as log:
        proc = subprocess.Popen(
            [str(VENV_PYTHON), str(COMFYUI_MAIN), "--port", "8188"],
            cwd=str(COMFYUI_ROOT), stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=flags)
    print("[server] started ComfyUI (PID %s) - waiting for it to come up ..." % proc.pid, flush=True)
    start = time.time()
    with tqdm(total=poll_timeout, desc="server startup", unit="s", dynamic_ncols=True) as bar:
        while time.time() - start < poll_timeout:
            if server_healthy():
                detail = "started fresh (PID %s) at %s" % (proc.pid, COMFYUI_URL)
                print("\n[server] healthy after %s" % human_time(time.time() - start), flush=True)
                return detail, True
            time.sleep(3)
            bar.update(3)
    return ("FAILED: no healthy response within %ss - check %s" % (poll_timeout, SERVER_LOG)), False


def fetch_system_stats() -> dict:
    try:
        d = http_session.get(COMFYUI_URL + "/system_stats", timeout=10).json()
        sysinfo = d.get("system", {})
        dev = (d.get("devices") or [{}])[0]
        return {
            "comfyui_version": sysinfo.get("comfyui_version", "?"),
            "python_version": sysinfo.get("python_version", "?"),
            "pytorch_version": sysinfo.get("pytorch_version", "?"),
            "gpu_name": dev.get("name", "?"),
            "vram_total_mb": round(dev.get("vram_total", 0) / (1024 * 1024)),
        }
    except Exception:
        return {}


# --------------------------------------------------------------------------
# Step 3: story generation (Ollama -> template fallback)
# --------------------------------------------------------------------------
def ollama_models():
    try:
        r = requests.get(OLLAMA_URL + "/api/tags", timeout=1.5)
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return []


def pick_llm(requested: str):
    available = ollama_models()
    if not available:
        return None
    if requested in available:
        return requested
    for pref in ("llama3.1:8b", "gemma4:latest", "qwen3.5:9b", "llama3:8b-instruct-q4_0"):
        if pref in available:
            return pref
    for name in available:
        if any(k in name.lower() for k in ("llama", "gemma", "qwen", "mistral")):
            return name
    return None


def template_story(theme: str) -> str:
    return ("%s. A cheerful cast of cute rounded characters with big sparkling eyes "
            "plays together in a bright pastel wonderland. Soft fluffy clouds drift "
            "overhead, glossy balloons bob through the air and gentle sparkles swirl "
            "around the scene. The characters bounce, clap and giggle in a playful "
            "rhythm while the camera glides slowly forward through warm golden light."
            % theme)


def generate_story(theme: str, requested_model: str):
    """Expand a theme into a visual scene story. Returns (story, source)."""
    model = pick_llm(requested_model)
    if model:
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": STORY_SYSTEM},
                    {"role": "user", "content": "Theme: %s" % theme},
                ],
                "stream": False,
                "options": {"temperature": 0.9, "num_predict": 400},
            }
            r = http_session.post(OLLAMA_URL + "/api/chat", json=payload, timeout=300)
            r.raise_for_status()
            text = (r.json().get("message", {}) or {}).get("content", "")
            text = re.sub(r"\s+", " ", text).strip().strip('"').strip()
            if len(text) >= 80:
                print("[story] written by ollama:%s" % model, flush=True)
                return text, "ollama:%s" % model
        except Exception as e:
            print("[story] Ollama failed (%s) - using template fallback" % e, flush=True)
    else:
        print("[story] Ollama not available - using template fallback", flush=True)
    return template_story(theme), "template-fallback"


# --------------------------------------------------------------------------
# Step 4: workflow + ComfyUI API
# --------------------------------------------------------------------------
def build_workflow(positive, seed, steps, cfg, width, height, length, fps):
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                         "type": "wan", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": positive}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": NEGATIVE_PROMPT}},
        "6": {"class_type": "EmptyHunyuanLatentVideo",
              "inputs": {"width": width, "height": height, "length": length, "batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "uni_pc",
                         "scheduler": "simple", "denoise": 1, "model": ["1", 0],
                         "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "CreateVideo",
              "inputs": {"images": ["8", 0], "fps": fps, "codec": "auto"}},
        "10": {"class_type": "SaveVideo",
               "inputs": {"video": ["9", 0], "filename_prefix": "video/baby_rhymes", "format": "auto"}},
    }


def post_workflow(workflow: dict) -> str:
    r = http_session.post(COMFYUI_URL + "/prompt",
                      json={"prompt": workflow, "client_id": CLIENT_ID}, timeout=60)
    if r.status_code != 200:
        try:
            err = r.json()
            msg = err.get("error", {}).get("message", r.text[:400])
            node_errs = err.get("node_errors", {}) or {}
            details = "; ".join("node %s: %s" % (nid, ne) for nid, ne in node_errs.items())
            raise RuntimeError(("workflow rejected: %s %s" % (msg, details))[:800])
        except ValueError:
            raise RuntimeError("workflow rejected: HTTP %s: %s" % (r.status_code, r.text[:400]))
    pid = r.json().get("prompt_id")
    if not pid:
        raise RuntimeError("no prompt_id in response: %s" % str(r.json())[:300])
    return pid


def extract_execution_error(entry: dict, status: dict) -> str:
    for msg in status.get("messages", []):
        if isinstance(msg, (list, tuple)) and len(msg) >= 2 and "error" in str(msg[0]):
            d = msg[1] if isinstance(msg[1], dict) else {}
            return "%s in node %s: %s" % (d.get("exception_type", "Error"),
                                          d.get("node_id", d.get("node", "?")),
                                          d.get("exception_message", str(d)[:300]))
    return "execution failed (see %s)" % SERVER_LOG


def poll_prompt(prompt_id: str, timeout_sec: int, eta_sec: int, poll_interval: int = 10):
    """Poll history until the prompt completes. Time-based bar + queue position.

    Returns (history_entry, elapsed_seconds). Raises on error/timeout.
    """
    start = time.time()
    failures = 0
    bar = tqdm(total=eta_sec, desc="rendering", unit="s", dynamic_ncols=True)
    try:
        while True:
            elapsed = time.time() - start
            if elapsed > timeout_sec:
                raise TimeoutError("generation exceeded %d minutes" % (timeout_sec // 60))

            state = "rendering"
            try:
                q = http_session.get(COMFYUI_URL + "/queue", timeout=5).json()
                running = [it[1] for it in q.get("queue_running", [])]
                pending = [it[1] for it in q.get("queue_pending", [])]
                if prompt_id in pending:
                    state = "queued #%d" % (pending.index(prompt_id) + 1)
                elif prompt_id in running:
                    state = "rendering"
                failures = 0
            except requests.RequestException:
                failures += 1
                state = "connection lost"
                if failures >= 6 and not server_healthy():
                    raise RuntimeError("ComfyUI server went down during generation - check %s" % SERVER_LOG)

            try:
                h = http_session.get(COMFYUI_URL + "/history/%s" % prompt_id, timeout=5).json()
                if prompt_id in h:
                    entry = h[prompt_id]
                    status = entry.get("status", {}) or {}
                    if status.get("status_str") == "error":
                        raise RuntimeError(extract_execution_error(entry, status))
                    if status.get("completed", status.get("completed_str", False)) \
                            or status.get("status_str") == "success":
                        return entry, elapsed
            except requests.RequestException:
                pass

            bar.n = min(int(elapsed), bar.total)
            bar.set_postfix_str(state)
            bar.refresh()
            time.sleep(poll_interval)
    finally:
        bar.close()


# --------------------------------------------------------------------------
# Step 5: output probing
# --------------------------------------------------------------------------
def probe_video(path: Path) -> dict:
    try:
        import av
        with av.open(str(path)) as c:
            s = c.streams.video[0]
            dur = (c.duration / 1_000_000.0) if c.duration else None
            if dur is None and s.duration is not None:
                dur = float(s.duration * s.time_base)
            cc = s.codec_context
            return {
                "duration_sec": round(dur, 2) if dur else None,
                "format": path.suffix.lstrip(".") or "unknown",
                "codec": getattr(cc, "name", None),
                "width": getattr(cc, "width", None),
                "height": getattr(cc, "height", None),
                "fps": round(float(s.average_rate), 2) if s.average_rate else None,
                "size_mb": round(path.stat().st_size / (1024 * 1024), 1),
            }
    except Exception as e:
        return {"probe_error": str(e)}


def extract_video_info(entry: dict):
    """Find the saved video in the history outputs and probe it."""
    for node_id, node_out in (entry.get("outputs", {}) or {}).items():
        if not isinstance(node_out, dict):
            continue
        for key in ("videos", "gifs", "images"):
            items = node_out.get(key)
            if not items:
                continue
            item = items[0]
            filename = item.get("filename", "")
            subfolder = item.get("subfolder", "")
            ftype = item.get("type", "output")
            base = OUTPUT_DIR if ftype != "temp" else COMFYUI_ROOT / "temp"
            path = base / subfolder / filename
            info = {"node": node_id, "filename": filename, "subfolder": subfolder,
                    "path": str(path)}
            if path.exists():
                info.update(probe_video(path))
            else:
                info["probe_error"] = "output file not found on disk"
            return info
    return None


# --------------------------------------------------------------------------
# Step 6: markdown report
# --------------------------------------------------------------------------
def write_report(report: dict, path: Path) -> None:
    lines = []
    a = lines.append
    a("# Baby Rhymes Generation Report")
    a("")
    a("- **Started:** %s" % report.get("started", "?"))
    a("- **Finished:** %s" % report.get("finished", "(in progress)"))
    if report.get("total_seconds"):
        a("- **Total time:** %s" % human_time(report["total_seconds"]))
    a("- **Command:** `%s`" % md_cell(" ".join(report.get("command", []))))
    sysinfo = report.get("system", {}) or {}
    if sysinfo:
        a("- **ComfyUI:** %s | **Python:** %s | **PyTorch:** %s" % (
            sysinfo.get("comfyui_version", "?"), sysinfo.get("python_version", "?"),
            sysinfo.get("pytorch_version", "?")))
        a("- **GPU:** %s (%s MB VRAM)" % (sysinfo.get("gpu_name", "?"),
                                          sysinfo.get("vram_total_mb", "?")))
    a("")

    a("## Preflight")
    a("")
    a("| Time | Step | Detail | Status |")
    a("|---|---|---|---|")
    for s in report.get("preflight", []):
        a("| %s | %s | %s | %s |" % (s["time"], md_cell(s["step"]),
                                     md_cell(s["detail"]), s["status"]))
    a("")

    videos = report.get("videos", [])
    a("## Summary")
    a("")
    a("| # | Theme | Status | Story | Duration | Format | Resolution | Output | Error |")
    a("|---|---|---|---|---|---|---|---|---|")
    for i, v in enumerate(videos, 1):
        vi = v.get("video") or {}
        a("| %d | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            i, md_cell(v.get("theme")), v.get("status", "?"),
            md_cell(v.get("story_source")), md_cell(vi.get("duration_sec", "")),
            md_cell(vi.get("format", "")),
            md_cell("%sx%s" % (vi.get("width", "?"), vi.get("height", "?")) if vi.get("width") else ""),
            md_cell(vi.get("filename", "")), md_cell(v.get("error", ""))))
    a("")

    for i, v in enumerate(videos, 1):
        vi = v.get("video") or {}
        a("## Video %d - %s" % (i, md_cell(v.get("theme"))))
        a("")
        a("- **Status:** %s" % v.get("status", "?"))
        a("- **Story source:** %s" % v.get("story_source", "?"))
        a("- **Seed:** %s | **Steps:** %s | **CFG:** %s | **Size:** %sx%s, %s frames @ %s fps" % (
            v.get("seed"), v.get("sampler_steps"), v.get("cfg"), v.get("width"), v.get("height"),
            v.get("frames"), v.get("fps")))
        if v.get("render_seconds") is not None:
            a("- **Render time:** %s" % human_time(v["render_seconds"]))
        a("")
        if v.get("story"):
            a("**Story:**")
            a("")
            a("> %s" % md_cell(v["story"]))
            a("")
        if v.get("positive_prompt"):
            a("**Positive prompt:**")
            a("")
            a("> %s" % md_cell(v["positive_prompt"]))
            a("")
        a("**Processing steps:**")
        a("")
        a("| # | Time | Step | Detail | Status |")
        a("|---|---|---|---|---|")
        for j, s in enumerate(v.get("steps", []), 1):
            a("| %d | %s | %s | %s | %s |" % (j, s["time"], md_cell(s["step"]),
                                             md_cell(s["detail"]), s["status"]))
        a("")
        if vi:
            a("**Output video:**")
            a("")
            a("- **Title:** %s" % md_cell(vi.get("filename", "?")))
            a("- **Path:** `%s`" % md_cell(vi.get("path", "?")))
            a("- **Duration:** %s s | **Format:** %s (%s) | **Resolution:** %sx%s | **FPS:** %s | **Size:** %s MB" % (
                vi.get("duration_sec", "?"), vi.get("format", "?"), vi.get("codec", "?"),
                vi.get("width", "?"), vi.get("height", "?"), vi.get("fps", "?"),
                vi.get("size_mb", "?")))
            if vi.get("probe_error"):
                a("- **Probe error:** %s" % md_cell(vi["probe_error"]))
            a("")
        a("**Errors:** %s" % (md_cell(v.get("error", "")) or "none"))
        a("")

    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def parse_args(argv):
    p = argparse.ArgumentParser(
        description="One-click WAN 2.2 baby-rhymes video generator (ComfyUI + Ollama).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Examples:\n  %(prog)s "a giggling baby elephant splashing in a bubbly pond"\n'
               '  %(prog)s --list themes.txt --seed 7\n  %(prog)s --check')
    p.add_argument("themes", nargs="*", help="theme(s) to turn into videos (quote multi-word themes)")
    p.add_argument("--list", metavar="FILE", help="file with one theme per line")
    p.add_argument("--report", default=str(DEFAULT_REPORT), help="markdown report path")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--steps", type=int, default=20, help="KSampler steps (default 20)")
    p.add_argument("--cfg", type=float, default=5.0, help="KSampler CFG (default 5)")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=704)
    p.add_argument("--frames", type=int, default=121, help="latent frames (121 ~= 5 s at 24 fps)")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--timeout-minutes", type=int, default=180, help="per-video generation timeout")
    p.add_argument("--eta-minutes", type=int, default=115, help="rough per-video render time for the progress bar")
    p.add_argument("--llm-model", default="llama3.1:8b", help="Ollama model for the story")
    p.add_argument("--server-timeout", type=int, default=300, help="seconds to wait for server startup")
    p.add_argument("--check", action="store_true", help="run preflight checks only (no generation)")
    return p.parse_args(argv)


def collect_themes(args):
    themes = [t.strip() for t in args.themes if t.strip()]
    if args.list:
        lf = Path(args.list)
        themes += [ln.strip() for ln in lf.read_text(encoding="utf-8", errors="ignore").splitlines()
                   if ln.strip() and not ln.strip().startswith("#")]
    if not themes:
        print("[themes] none given - using built-in demo theme", flush=True)
        themes = list(DEFAULT_THEMES)
    return themes


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    report_path = Path(args.report)
    report = {"started": now_iso(), "command": sys.argv, "preflight": [], "videos": []}
    print("=" * 70, flush=True)
    print(" gtracking baby-rhymes generator - WAN 2.2 TI2V-5B via ComfyUI", flush=True)
    print("=" * 70, flush=True)

    try:
        # ---- preflight -------------------------------------------------
        report["preflight"].append(step("venv", "running under %s" % sys.executable))
        model_steps, models_ok = ensure_models()
        report["preflight"].extend(model_steps)
        server_detail, server_ok = ensure_server(args.server_timeout)
        report["preflight"].append(step("ComfyUI server", server_detail,
                                        "ok" if server_ok else "error"))
        report["system"] = fetch_system_stats()
        if not (models_ok and server_ok):
            report["finished"] = now_iso()
            write_report(report, report_path)
            print("[FATAL] preflight failed - see %s" % report_path, flush=True)
            return 1
        if args.check:
            test_theme = collect_themes(args)[0]
            story, source = generate_story(test_theme, args.llm_model)
            report["preflight"].append(step(
                "story test", "theme expanded via %s (%d chars)" % (source, len(story))))
            report["check_story"] = story
            report["finished"] = now_iso()
            write_report(report, report_path)
            print("[check] preflight OK - venv, models, server and story generation all working.")
            print("[check] sample story (%s): %s" % (source, story[:200]), flush=True)
            print("[check] report: %s" % report_path, flush=True)
            return 0

        # ---- per-theme generation -------------------------------------
        themes = collect_themes(args)
        started = time.time()
        failures = 0
        for i, theme in enumerate(themes, 1):
            print("\n[%d/%d] theme: %s" % (i, len(themes), theme), flush=True)
            vid = {"theme": theme, "status": "error", "steps": [], "seed": args.seed + i - 1,
                   "sampler_steps": args.steps, "cfg": args.cfg, "width": args.width, "height": args.height,
                   "frames": args.frames, "fps": args.fps, "story_source": None, "story": None,
                   "positive_prompt": None, "video": None, "error": None, "render_seconds": None}
            t0 = time.time()
            try:
                vid["steps"].append(step("story", "expanding theme with local LLM"))
                story, source = generate_story(theme, args.llm_model)
                vid["story"], vid["story_source"] = story, source
                vid["steps"].append(step("story", "written via %s" % source))

                positive = "3D animated baby-rhyme video: %s, %s" % (story, STYLE_SUFFIX)
                vid["positive_prompt"] = positive
                vid["steps"].append(step("workflow", "built WAN 2.2 graph (seed %d, %d steps, "
                                          "%dx%d, %d frames @ %d fps)" % (vid["seed"], args.steps,
                                          args.width, args.height, args.frames, args.fps)))

                prompt_id = post_workflow(build_workflow(
                    positive, vid["seed"], args.steps, args.cfg, args.width,
                    args.height, args.frames, args.fps))
                vid["steps"].append(step("submit", "prompt_id %s" % prompt_id))
                print("[submit] prompt_id %s - rendering (expect ~%d min) ..." % (prompt_id, args.eta_minutes), flush=True)

                entry, elapsed = poll_prompt(prompt_id, args.timeout_minutes * 60,
                                             args.eta_minutes * 60)
                vid["render_seconds"] = elapsed
                vid["steps"].append(step("render", "completed in %s" % human_time(elapsed)))

                vinfo = extract_video_info(entry)
                if not vinfo:
                    raise RuntimeError("no video found in workflow outputs - check %s" % SERVER_LOG)
                vid["video"] = vinfo
                vid["status"] = "success"
                vid["steps"].append(step("output", "%s (%s MB)" % (vinfo.get("filename", "?"),
                                                                  vinfo.get("size_mb", "?"))))
                print("[done] %s -> %s" % (vinfo.get("filename", "?"), vinfo.get("path", "?")), flush=True)
            except Exception as e:
                failures += 1
                vid["error"] = str(e)
                vid["steps"].append(step("error", str(e), "error"))
                print("[ERROR] %s" % e, flush=True)
            vid["total_seconds"] = time.time() - t0
            report["videos"].append(vid)
            write_report(report, report_path)  # incremental save after each video

        report["finished"] = now_iso()
        report["total_seconds"] = time.time() - started
        write_report(report, report_path)
        ok = len(report["videos"]) - failures
        print("\n" + "=" * 70, flush=True)
        print(" done: %d/%d videos generated | report: %s" % (ok, len(report["videos"]), report_path), flush=True)
        print("=" * 70, flush=True)
        return 1 if failures else 0
    except KeyboardInterrupt:
        report["finished"] = now_iso() + " (interrupted)"
        write_report(report, report_path)
        print("\n[interrupted] partial report written to %s" % report_path, flush=True)
        return 130
    except Exception as e:
        report["finished"] = now_iso() + " (crashed)"
        report["crash"] = str(e)
        write_report(report, report_path)
        print("[FATAL] %s - report: %s" % (e, report_path), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
