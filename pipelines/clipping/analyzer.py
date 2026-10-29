"""Highlight detection analyzer using local LLM (Ollama) and heuristic fallbacks."""

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class HighlightAnalyzer:
    """Detects engaging viral highlights from transcriptions."""

    def __init__(self, config: dict):
        self.config = config

    def _load_instructions(self, category: Optional[str] = None) -> str:
        candidates = []
        if category:
            candidates.append(Path("instructions") / f"{category}.md")
        candidates.append(Path("instructions") / "default.md")
        candidates.append(Path("editing_instructions.md"))
        for path in candidates:
            if path.exists():
                return path.read_text(encoding="utf-8")
        return 'Pick the most engaging 30-60 second segment. Respond with JSON: [{"clip_start": float, "clip_end": float, "title": str}]'

    def _ask_llm(self, prompt: str) -> list:
        import requests
        llm_cfg = self.config.get("llm", {})
        endpoint = str(llm_cfg.get("endpoint", "http://localhost:11434")).rstrip("/")
        model = llm_cfg.get("model", "llama3.1:8b")
        resp = requests.post(
            f"{endpoint}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=300,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
        arr_start, arr_end = text.find("["), text.rfind("]")
        obj_start, obj_end = text.find("{"), text.rfind("}")
        if arr_start != -1 and arr_end != -1 and (obj_start == -1 or arr_start < obj_start):
            return json.loads(text[arr_start:arr_end + 1])
        if obj_start != -1 and obj_end != -1:
            data = json.loads(text[obj_start:obj_end + 1])
            return [data] if isinstance(data, dict) else data
        raise ValueError(f"LLM returned no valid JSON: {text[:200]}")

    async def find_highlights(
        self,
        video_path: str,
        transcription: dict,
        task_id: str,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find highlight segments via LLM, falling back to heuristic."""
        segments = transcription.get("segments") or []
        if not segments:
            return await self._heuristic_fallback(video_path)

        duration = segments[-1].get("end", 0)
        transcript = "\n".join(f"[{s['start']:.1f}] {s['text'].strip()}" for s in segments)
        instructions = self._load_instructions(category)
        max_clips = int(self.config.get("max_clips_per_video", 5))

        prompt = (
            f"{instructions}\n\n"
            f"Select up to {max_clips} of the best segments (engaging, high energy, complete thought). "
            f'Respond with JSON array: [{{"clip_start": float, "clip_end": float, "title": str, "reason": str}}, ...]\n\n'
            f"TRANSCRIPT:\n{transcript}\n"
        )

        loop = asyncio.get_event_loop()
        try:
            items = await loop.run_in_executor(None, self._ask_llm, prompt)
            highlights = []
            for item in items[:max_clips]:
                if not isinstance(item, dict):
                    continue
                start = max(0.0, float(item.get("clip_start", 0)))
                end = min(float(duration), float(item.get("clip_end", 60)))
                if end - start < 15:
                    end = min(float(duration), start + 30)
                if end - start > 90:
                    end = start + 60
                if end > start:
                    title = re.sub(r"[^\w\s-]", "", str(item.get("title", "highlight"))).strip() or "highlight"
                    highlights.append({"start": start, "end": end, "title": title})
            if highlights:
                return highlights
        except Exception as e:
            logger.warning(f"[{task_id}] AI highlight detection failed: {e}")

        return await self._heuristic_fallback(video_path)

    async def _heuristic_fallback(self, video_path: str) -> List[Dict[str, Any]]:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        duration = float(stdout.decode().strip()) if stdout else 60.0

        clip_duration = min(60.0, duration)
        max_clips = int(self.config.get("max_clips_per_video", 3))
        num_clips = min(max_clips, max(1, int(duration / clip_duration)))

        return [{"start": i * clip_duration, "end": min((i + 1) * clip_duration, duration), "title": f"highlight_{i+1}"} for i in range(num_clips)]
