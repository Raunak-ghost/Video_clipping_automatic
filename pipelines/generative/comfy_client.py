"""ComfyUI API Client with persistent socket pooling."""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm

COMFYUI_ROOT = Path(r"D:\ComfyUI\ComfyUI")
COMFYUI_MAIN = COMFYUI_ROOT / "main.py"
COMFYUI_VENV_PYTHON = Path(r"D:\ComfyUI\venv\Scripts\python.exe")
COMFYUI_URL = "http://127.0.0.1:8188"
SERVER_LOG = Path(r"D:\ComfyUI\comfyui_server.log")
OUTPUT_DIR = COMFYUI_ROOT / "output"

CLIENT_ID = "video-clipping-generative"


class ComfyClient:
    """Connection-pooled client for ComfyUI."""

    def __init__(self, base_url: str = COMFYUI_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retries)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def is_healthy(self, timeout: float = 3.0) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/system_stats", timeout=timeout)
            return r.status_code == 200
        except Exception:
            return False

    def build_wan22_workflow(self, **kwargs) -> Dict[str, Any]:
        """Construct WAN 2.2 graph via workflow_builder."""
        from .workflow_builder import build_wan22_workflow
        return build_wan22_workflow(**kwargs)

    def ensure_server(self, poll_timeout: int = 180) -> bool:
        """Start the ComfyUI server if not already running."""
        if self.is_healthy():
            return True

        if not COMFYUI_MAIN.exists():
            print(f"[ERROR] ComfyUI entrypoint not found: {COMFYUI_MAIN}", file=sys.stderr)
            return False

        SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
        py_exec = str(COMFYUI_VENV_PYTHON) if COMFYUI_VENV_PYTHON.exists() else sys.executable
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        with open(SERVER_LOG, "ab") as log:
            proc = subprocess.Popen(
                [py_exec, str(COMFYUI_MAIN), "--port", "8188"],
                cwd=str(COMFYUI_ROOT),
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
            )

        print(f"[*] Started ComfyUI server (PID {proc.pid}) — waiting for readiness...")
        start = time.time()
        with tqdm(total=poll_timeout, desc="Starting ComfyUI", unit="s", dynamic_ncols=True) as bar:
            while time.time() - start < poll_timeout:
                if self.is_healthy():
                    print("\n[OK] ComfyUI server ready.")
                    return True
                time.sleep(2)
                bar.update(2)

        print(f"[ERROR] ComfyUI failed to start within {poll_timeout}s. Check {SERVER_LOG}", file=sys.stderr)
        return False

    def submit_prompt(self, workflow: Dict[str, Any]) -> str:
        r = self.session.post(
            f"{self.base_url}/prompt",
            json={"prompt": workflow, "client_id": CLIENT_ID},
            timeout=60,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Workflow rejected by ComfyUI (HTTP {r.status_code}): {r.text[:400]}")
        prompt_id = r.json().get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"No prompt_id returned: {r.text[:200]}")
        return prompt_id

    def poll_execution(
        self,
        prompt_id: str,
        timeout_sec: int = 7200,
        eta_sec: int = 1200,
        poll_interval: int = 5,
    ) -> Tuple[Dict[str, Any], float]:
        """Poll prompt execution history with keep-alive socket reuse."""
        start = time.time()
        failures = 0
        with tqdm(total=eta_sec, desc="Rendering Video", unit="s", dynamic_ncols=True) as bar:
            while True:
                elapsed = time.time() - start
                if elapsed > timeout_sec:
                    raise TimeoutError(f"Rendering exceeded timeout limit of {timeout_sec // 60}m")

                # Check history first: if completed, return immediately
                try:
                    h = self.session.get(f"{self.base_url}/history/{prompt_id}", timeout=15).json()
                    if prompt_id in h:
                        entry = h[prompt_id]
                        status = entry.get("status", {}) or {}
                        if status.get("status_str") == "error":
                            raise RuntimeError(f"ComfyUI node execution error in prompt {prompt_id}")
                        if status.get("completed", False) or status.get("status_str") == "success":
                            return entry, elapsed
                    failures = 0
                except (requests.RequestException, Exception):
                    failures += 1

                # Check queue for status update
                try:
                    q = self.session.get(f"{self.base_url}/queue", timeout=15).json()
                    running = [it[1] for it in q.get("queue_running", [])]
                    pending = [it[1] for it in q.get("queue_pending", [])]
                    if prompt_id in pending:
                        bar.set_postfix_str(f"queued #{pending.index(prompt_id) + 1}")
                    elif prompt_id in running:
                        bar.set_postfix_str("sampling / decoding")
                    failures = 0
                except (requests.RequestException, Exception):
                    failures += 1
                    bar.set_postfix_str("reconnecting / busy")
                    # ROCm VAE decode locks GIL for up to 2-3 mins; only abort after 30 consecutive failures (5+ min)
                    if failures >= 30 and not self.is_healthy(timeout=10.0):
                        raise RuntimeError(f"ComfyUI server unreachable — inspect {SERVER_LOG}")

                bar.n = min(int(elapsed), bar.total)
                bar.refresh()
                time.sleep(poll_interval)

    def extract_output_path(self, entry: Dict[str, Any]) -> Optional[Path]:
        """Extract output file path from completed history entry."""
        outputs = entry.get("outputs", {}) or {}
        for node_id, node_out in outputs.items():
            if not isinstance(node_out, dict):
                continue
            for key in ("videos", "gifs", "images"):
                items = node_out.get(key)
                if items and isinstance(items, list):
                    item = items[0]
                    filename = item.get("filename", "")
                    subfolder = item.get("subfolder", "")
                    ftype = item.get("type", "output")
                    base = OUTPUT_DIR if ftype != "temp" else COMFYUI_ROOT / "temp"
                    candidate = base / subfolder / filename
                    if candidate.exists():
                        return candidate
        return None
