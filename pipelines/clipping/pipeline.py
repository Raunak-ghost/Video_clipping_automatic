"""Orchestrated Video Clipping Pipeline."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from core.config import load_config
from core.hardware import get_encoder_cascade
from core.styles import resolve_style

from .downloader import VideoDownloader
from .transcriber import VideoTranscriber
from .analyzer import HighlightAnalyzer
from .renderer import VideoRenderer

logger = logging.getLogger(__name__)


class ClipperPipeline:
    """Cohesive pipeline connecting downloader -> transcriber -> analyzer -> renderer."""

    def __init__(self, db):
        self.db = db
        self.config = load_config()
        self.base_clips_dir = Path(self.config.get("clips_dir", "clips"))
        self.base_downloads_dir = Path(self.config.get("downloads_dir", "downloads"))
        self.ffmpeg_path = self.config.get("ffmpeg_path", "ffmpeg")

        self.encoders = get_encoder_cascade(self.ffmpeg_path, preferred_encoder=self.config.get("encoder"))
        self.downloader = VideoDownloader(self.base_downloads_dir, self.config)
        self.transcriber = VideoTranscriber(self.config.get("whisper_model", "base"))
        self.analyzer = HighlightAnalyzer(self.config)
        self.renderer = VideoRenderer(self.ffmpeg_path, self.encoders)

        self.base_clips_dir.mkdir(parents=True, exist_ok=True)
        self.base_downloads_dir.mkdir(parents=True, exist_ok=True)

    async def process_video(
        self,
        video_url: str,
        task_id: str,
        category: Optional[str] = None,
        channel_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Full pipeline: download -> transcribe -> highlight -> render."""
        self.db.update_task_status(task_id, "processing", progress=10.0)

        try:
            # Step 1: Download
            self.db.update_task_status(task_id, "processing", progress=20.0)
            video_path = await self.downloader.download(video_url, task_id)
            if not video_path:
                raise RuntimeError("Failed to download video")

            # Step 2: Transcribe
            self.db.update_task_status(task_id, "processing", progress=40.0)
            loop = asyncio.get_event_loop()
            transcription = await loop.run_in_executor(None, self.transcriber.transcribe, video_path)

            # Step 3: Analyze Highlights
            self.db.update_task_status(task_id, "processing", progress=60.0)
            highlights = await self.analyzer.find_highlights(video_path, transcription, task_id, category)

            # Step 4: Render
            self.db.update_task_status(task_id, "processing", progress=80.0)
            clip_paths = []
            style = resolve_style(category, self.config)
            date_str = datetime.now().strftime("%Y-%m-%d")

            output_dir = self.base_clips_dir / (category or "uncategorized") / (channel_name or "unknown") / date_str
            output_dir.mkdir(parents=True, exist_ok=True)

            for i, h in enumerate(highlights):
                safe_title = "".join(c for c in h.get("title", f"clip_{i}") if c.isalnum() or c in " _-").strip()
                out_path = output_dir / f"{task_id}_{safe_title}_{int(h['start'])}_{int(h['end'])}.mp4"

                rendered = await self.renderer.render_clip(
                    video_path=video_path,
                    clip_start=h["start"],
                    clip_end=h["end"],
                    output_path=str(out_path),
                    style=style,
                    transcription=transcription,
                )
                if rendered:
                    clip_paths.append(rendered)
                    self.db.create_clip_metadata(
                        task_id=task_id,
                        clip_start=h["start"],
                        clip_end=h["end"],
                        duration=h["end"] - h["start"],
                        output_path=rendered,
                        social_platform="youtube",
                        title=h.get("title", ""),
                        category=category,
                        channel=channel_name,
                    )

            self.db.update_task_status(task_id, "completed", progress=100.0, clip_path=clip_paths[0] if clip_paths else None)
            return {"status": "completed", "task_id": task_id, "clips": clip_paths}

        except Exception as e:
            logger.error(f"[{task_id}] Clipper pipeline failed: {e}")
            self.db.update_task_status(task_id, "failed", error=str(e))
            return {"status": "failed", "task_id": task_id, "error": str(e)}

    async def edit_video_clip(
        self,
        video_path: str,
        clip_start: float,
        clip_end: float,
        output_path: str,
        aspect_ratio: str = "original",
        task_id: Optional[str] = None,
        title: Optional[str] = None,
        style: str = "subtitles",
    ) -> str:
        """Edit and style an individual clip directly."""
        loop = asyncio.get_event_loop()
        transcription = await loop.run_in_executor(None, self.transcriber.transcribe, video_path)
        return await self.renderer.render_clip(
            video_path=video_path,
            clip_start=clip_start,
            clip_end=clip_end,
            output_path=output_path,
            style=style,
            transcription=transcription,
            aspect_ratio=aspect_ratio,
        )
