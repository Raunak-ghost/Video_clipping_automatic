"""Generative AI Video Pipeline Orchestrator."""

import logging
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional

import requests
from .comfy_client import ComfyClient
from .workflow_builder import build_wan22_workflow
from pipelines.styles import get_style

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"


class GenerativePipeline:
    """End-to-end pipeline for text-to-video diffusion generation."""

    def __init__(self, client: Optional[ComfyClient] = None):
        self.client = client or ComfyClient()

    def expand_story(self, theme: str, model: str = "llama3.1:8b") -> str:
        """Expand a raw user theme using local Ollama or template fallback."""
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
            if r.status_code == 200:
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You write visual scene descriptions for text-to-video AI. "
                                "Given a theme, write ONE continuous scene description (60-100 words, present tense). "
                                "Concrete visual language only. Reply with the scene description only."
                            ),
                        },
                        {"role": "user", "content": f"Theme: {theme}"},
                    ],
                    "stream": False,
                }
                res = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=30)
                if res.status_code == 200:
                    text = (res.json().get("message", {}) or {}).get("content", "").strip()
                    if len(text) > 40:
                        return re.sub(r"\s+", " ", text)
        except Exception:
            pass

        return (
            f"{theme}. A beautifully rendered cinematic scene with vivid colors, "
            f"natural motion, elegant volumetric lighting, and high visual clarity. "
            f"The camera moves slowly and smoothly across the setting."
        )

    def generate_video(
        self,
        theme: str,
        style: str = "kids",
        seed: int = 42,
        steps: int = 20,
        cfg: float = 5.0,
        width: int = 1280,
        height: int = 704,
        frames: int = 121,
        fps: int = 24,
    ) -> Dict[str, Any]:
        """Execute full video generation."""
        if not self.client.ensure_server(poll_timeout=120):
            raise RuntimeError("ComfyUI server failed to start")

        story = self.expand_story(theme)
        style_handler = get_style(style, client=self.client)

        workflow = style_handler.generate(
            prompt=story,
            seed=seed,
            steps=steps,
            cfg=cfg,
            width=width,
            height=height,
            frames=frames,
            fps=fps,
        )

        prompt_id = self.client.submit_prompt(workflow)
        entry, elapsed = self.client.poll_execution(prompt_id)
        out_path = self.client.extract_output_path(entry)

        return {
            "status": "completed",
            "prompt_id": prompt_id,
            "style": style,
            "theme": theme,
            "story": story,
            "elapsed_seconds": elapsed,
            "output_path": str(out_path) if out_path else None,
        }
