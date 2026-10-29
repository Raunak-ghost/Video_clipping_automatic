"""FFmpeg Video Renderer & ASS Subtitle Generation module."""

import asyncio
import logging
from pathlib import Path
from typing import Optional, List

from core.styles import CAPTION_PRESETS, build_ffmpeg_filters

logger = logging.getLogger(__name__)


class VideoRenderer:
    """Renders styled clips with hardware-accelerated FFmpeg and burned-in subtitles."""

    def __init__(self, ffmpeg_path: str, encoders: List[str]):
        self.ffmpeg_path = ffmpeg_path
        self.encoders = encoders

    @staticmethod
    def _ass_timestamp(seconds: float) -> str:
        seconds = max(0.0, seconds)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int(round((seconds - int(seconds)) * 100))
        if cs == 100:
            s += 1
            cs = 0
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def generate_subtitles(
        self,
        transcription: dict,
        clip_start: float,
        clip_end: float,
        ass_path: Path,
        style: str = "subtitles",
    ) -> Path:
        segments = transcription.get("segments") or []
        words = []
        for seg in segments:
            for w in seg.get("words") or []:
                w_start, w_end = float(w.get("start", 0)), float(w.get("end", 0))
                if w_end <= clip_start or w_start >= clip_end:
                    continue
                words.append({
                    "start": max(0.0, w_start - clip_start),
                    "end": min(clip_end - clip_start, w_end - clip_start),
                    "word": str(w.get("word", "")).strip(),
                })

        if not words:
            for seg in segments:
                s_start, s_end = float(seg.get("start", 0)), float(seg.get("end", 0))
                if s_end <= clip_start or s_start >= clip_end:
                    continue
                words.append({
                    "start": max(0.0, s_start - clip_start),
                    "end": min(clip_end - clip_start, s_end - clip_start),
                    "word": str(seg.get("text", "")).strip(),
                })

        preset = CAPTION_PRESETS.get(style, CAPTION_PRESETS["subtitles"])
        header = (
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Words,{preset['font']},{preset['size']},{preset['colour']},&H00000000,&H80000000,"
            f"1,0,0,0,100,100,2,0,1,{preset['outline']},1,{preset['align']},40,40,{preset['margin_v']},1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        words_per_event = int(preset["words"])
        events = []
        for i in range(0, len(words), words_per_event):
            chunk = words[i:i + words_per_event]
            if not chunk:
                continue
            text = " ".join(w["word"] for w in chunk).strip()
            if not text:
                continue
            start = self._ass_timestamp(chunk[0]["start"])
            end = self._ass_timestamp(chunk[-1]["end"])
            events.append(f"Dialogue: 0,{start},{end},Words,,0,0,0,,{text}")

        ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
        return ass_path

    async def render_clip(
        self,
        video_path: str,
        clip_start: float,
        clip_end: float,
        output_path: str,
        style: str = "subtitles",
        transcription: Optional[dict] = None,
        aspect_ratio: str = "9:16",
    ) -> str:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        duration = clip_end - clip_start

        ass_escaped = None
        if transcription:
            ass_path = out_path.with_suffix(".ass")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self.generate_subtitles, transcription, clip_start, clip_end, ass_path, style
            )
            ass_escaped = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")

        vf, filter_complex = build_ffmpeg_filters(style, ass_escaped=ass_escaped, aspect_ratio=aspect_ratio)

        for encoder in self.encoders:
            cmd = [
                self.ffmpeg_path,
                "-ss", str(clip_start),
                "-i", video_path,
                "-t", str(duration),
                "-c:v", encoder,
                "-c:a", "aac",
                "-strict", "experimental",
                "-y",
            ]
            if filter_complex:
                cmd.extend(["-filter_complex", filter_complex])
            elif vf:
                cmd.extend(["-vf", vf])
            cmd.append(str(output_path))

            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                return str(output_path)
            logger.warning(f"Encoder {encoder} failed: {stderr.decode()[:200]}")

        raise RuntimeError("All configured FFmpeg encoders failed")
