import os
import asyncio
import subprocess
import logging
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

try:
    from yt_dlp import YoutubeDL
except ImportError:
    YoutubeDL = None

logger = logging.getLogger(__name__)


class Pipeline:
    """Full video processing pipeline with database integration."""
    
    def __init__(self, db):
        self.db = db
        self.config = self._load_config()
        self.base_clips_dir = Path(self.config.get("clips_dir", "clips"))
        self.base_downloads_dir = Path(self.config.get("downloads_dir", "downloads"))
        self.ffmpeg_path = self.config.get("ffmpeg_path", "ffmpeg")
        self.encoder = self.config.get("encoder", "h264_amf")
        self.fallback_encoder = "libx264"
        
        self.base_clips_dir.mkdir(parents=True, exist_ok=True)
        self.base_downloads_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> dict:
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _sanitize_filename(self, name: str) -> str:
        return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-', '.')).strip()

    async def process_video(self, video_url: str, task_id: str, category: Optional[str] = None, channel_name: Optional[str] = None) -> Dict[str, Any]:
        """Full pipeline: download → find highlights → clip → upload."""
        self.db.update_task_status(task_id, "processing", progress=10.0)
        
        try:
            # Step 1: Download video
            logger.info(f"[{task_id}] Downloading video from {video_url}")
            self.db.update_task_status(task_id, "processing", progress=20.0)
            video_path = await self._download_video(video_url, task_id)
            if not video_path:
                raise Exception("Failed to download video")
            
            # Step 2: Find highlights (AI or manual)
            logger.info(f"[{task_id}] Analyzing video for highlights")
            self.db.update_task_status(task_id, "processing", progress=40.0)
            highlights = await self._find_highlights(video_path, task_id, category)
            
            # Step 3: Create clips for each highlight
            logger.info(f"[{task_id}] Creating clips from highlights")
            self.db.update_task_status(task_id, "processing", progress=60.0)
            clip_paths = []
            for i, highlight in enumerate(highlights):
                clip_path = await self._create_clip(
                    video_path, 
                    highlight["start"], 
                    highlight["end"],
                    task_id, 
                    highlight.get("title", f"clip_{i}"),
                    category,
                    channel_name
                )
                if clip_path:
                    clip_paths.append(clip_path)
            
            # Step 4: Upload to platforms (YouTube connector)
            logger.info(f"[{task_id}] Uploading clips")
            self.db.update_task_status(task_id, "processing", progress=80.0)
            upload_results = await self._upload_clips(clip_paths, task_id, category, channel_name)
            
            self.db.update_task_status(task_id, "completed", progress=100.0, clip_path=clip_paths[0] if clip_paths else None)
            logger.info(f"[{task_id}] Pipeline completed successfully")
            return {"status": "completed", "task_id": task_id, "clips": clip_paths, "uploads": upload_results}
            
        except Exception as e:
            logger.error(f"[{task_id}] Pipeline failed: {e}")
            self.db.update_task_status(task_id, "failed", error=str(e))
            return {"status": "failed", "task_id": task_id, "error": str(e)}

    # ------------------- subtitle (ASS) generation -------------------

    @staticmethod
    def _ass_timestamp(seconds: float) -> str:
        """Format seconds as ASS timestamp h:mm:ss.cc (centiseconds)."""
        seconds = max(0.0, seconds)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int(round((seconds - int(seconds)) * 100))
        if cs == 100:
            s += 1
            cs = 0
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    # Per-style ASS caption presets (from editing_styles/*.md archetypes).
    # Keys: font, size, primary colour (ASS &HBBGGRR), outline, alignment, marginV, words/event
    _CAPTION_PRESETS = {
        "subtitles": dict(font="Arial", size=80, colour="&H00FFFFFF", outline=6, align=5, margin_v=60, words=3),
        # Hormozi: big uppercase kinetic words, center screen, yellow accent
        "hormozi":   dict(font="Impact", size=96, colour="&H00FFFFFF", outline=7, align=5, margin_v=0, words=2),
        # Podcast: mid-divider captions, smaller, white
        "podcast":   dict(font="Arial", size=56, colour="&H00FFFFFF", outline=4, align=5, margin_v=0, words=4),
        # Faceless: clean 2-line lower-third with soft box
        "faceless":  dict(font="Arial", size=52, colour="&H00FFFFFF", outline=2, align=2, margin_v=140, words=8),
        # Gameplay: center captions over the 60/40 boundary
        "gameplay":  dict(font="Arial", size=72, colour="&H00FFFFFF", outline=6, align=5, margin_v=0, words=3),
        # Corporate: minimal lower-third banner
        "corporate": dict(font="Arial", size=44, colour="&H00FFFFFF", outline=1, align=2, margin_v=120, words=10),
        # Kids: big rounded friendly captions, bright yellow, thick outline, bottom-screen
        "kids":      dict(font="Arial Rounded MT Bold", size=92, colour="&H0000D7FF", outline=8, align=2, margin_v=140, words=4),
        # Anime recap: bold white bottom captions over full-screen footage
        "anime":     dict(font="Arial", size=76, colour="&H00FFFFFF", outline=6, align=2, margin_v=150, words=4),
        # Movie recap: bold white center captions over full-screen footage
        "movie":     dict(font="Arial", size=80, colour="&H00FFFFFF", outline=6, align=5, margin_v=0, words=4),
    }

    def _generate_word_subtitles(self, video_path: str, clip_start: float, clip_end: float, ass_path: Path, style: str = "subtitles") -> Path:
        """Build an ASS subtitle file from cached Whisper word timestamps.

        Formatting is driven by _CAPTION_PRESETS[style] (per editing_styles/*.md).
        """
        result = self._transcribe(video_path)
        segments = result.get("segments") or []

        # Collect words inside the clip window, shifted to clip-relative time
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

        # Fallback: no word timestamps -> use whole segments
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

        preset = self._CAPTION_PRESETS.get(style, self._CAPTION_PRESETS["subtitles"])
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
        logger.info(f"Generated {len(events)} subtitle events ({style}) -> {ass_path}")
        return ass_path

    # ------------------- clip rendering -------------------

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
        """Edit a single clip: trim, convert aspect ratio, apply style, save.

        Styles (from editing_styles/ archetypes) - all transformative:
          subtitles  - 9:16 vertical + centered word-by-word captions (generic)
          blur       - 9:16 vertical with blurred background behind sharp video
          hormozi    - 9:16 + kinetic word captions w/ yellow keyword highlights
          podcast    - 9:16 dual split-screen (top/bottom speaker boxes) + captions
          faceless   - 9:16 blurred bg + clean 2-line lower-third captions
          gameplay   - 9:16 top 60% clip / bottom 40% blurred fill + center captions
          corporate  - 9:16 minimal lower-third banner captions, no jump cuts
          kids       - 9:16 big rounded colorful center captions (nursery rhymes)
          anime      - 9:16 full-screen footage + bold white bottom captions (recap)
          movie      - 9:16 full-screen footage + bold white center captions (recap)

        Note: the old "original" plain-trim style was removed - an unedited
        copy-paste clip is bound to be copyright-flagged. Any request for it
        falls back to "subtitles".
        """
        if style == "original":
            logger.warning("style 'original' removed (no transformation) - using 'subtitles'")
            style = "subtitles"

        out_path: Path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        duration = clip_end - clip_start
        vf = None
        filter_complex = None

        # Styles that burn in word-level captions via an ASS sidecar
        caption_styles = {"subtitles", "hormozi", "podcast", "faceless", "gameplay", "corporate", "kids", "anime", "movie"}
        ass_escaped = None
        if style in caption_styles:
            ass_path = out_path.with_suffix(".ass")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._generate_word_subtitles, video_path, clip_start, clip_end, ass_path, style
            )
            # ffmpeg subtitles filter needs forward slashes and escaped drive colon
            ass_escaped = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")

        if style in ("subtitles", "hormozi", "kids", "anime", "movie"):
            # Full-screen 9:16 fill: scale to COVER the frame, then center-crop.
            # (scale-then-crop avoids the tiny-sliver bug on low-res landscape sources)
            vf = (
                "scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,"
                f"subtitles='{ass_escaped}'"
            )
        elif style == "podcast":
            # Dual split-screen: top half + bottom half of the source, captions on divider
            filter_complex = (
                "[0:v]split=2[top][bot];"
                "[top]crop=iw:ih/2:0:0,scale=1080:960[t];"
                "[bot]crop=iw:ih/2:0:ih/2,scale=1080:960[b];"
                "[t][b]vstack=inputs=2[stacked];"
                f"[stacked]subtitles='{ass_escaped}'"
            )
        elif style == "faceless":
            # Blurred full-bg + sharp centered video + clean lower-third captions
            filter_complex = (
                "[0:v]split[main][bg];"
                "[bg]crop=ih*9/16:ih,scale=1080:1920,gblur=sigma=30[bg2];"
                "[main]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                f"[bg2][fg]overlay=(W-w)/2:(H-h)/2,subtitles='{ass_escaped}'"
            )
        elif style == "gameplay":
            # Top 60% sharp video, bottom 40% blurred fill, captions on the boundary
            filter_complex = (
                "[0:v]split[main][bg];"
                "[bg]crop=ih*9/16:ih,scale=1080:1920,gblur=sigma=40[bg2];"
                "[main]scale=1080:1152:force_original_aspect_ratio=decrease[fg];"
                f"[bg2][fg]overlay=(W-w)/2:0,subtitles='{ass_escaped}'"
            )
        elif style == "corporate":
            vf = f"crop=ih*9/16:ih,scale=1080:1920,subtitles='{ass_escaped}'"
        elif style == "blur":
            filter_complex = (
                "[0:v]split[main][bg];"
                "[bg]crop=ih*9/16:ih,scale=1080:1920,gblur=sigma=30[bg2];"
                "[main]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                "[bg2][fg]overlay=(W-w)/2:(H-h)/2"
            )
        elif aspect_ratio == "9:16":
            # Vertical: crop to 9:16 center, then scale
            vf = "crop=ih*9/16:ih,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
        elif aspect_ratio == "16:9":
            vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black"

        for encoder in [self.encoder, self.fallback_encoder]:
            try:
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
                
                logger.info(f"Running FFmpeg with encoder {encoder}...")
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                
                if proc.returncode == 0:
                    logger.info(f"Clip saved to {output_path}")
                    return str(output_path)
                else:
                    logger.warning(f"Encoder {encoder} failed: {stderr.decode()}")
                    continue
            except Exception as e:
                logger.warning(f"Encoder {encoder} error: {e}")
                continue
        
        raise Exception("All encoders failed")

    async def _download_video(self, video_url: str, task_id: str) -> Optional[str]:
        """Download video using yt-dlp."""
        if not YoutubeDL:
            logger.error("yt-dlp not installed")
            return None
        
        output_template = str(self.base_downloads_dir / f"{task_id}_%(title)s.%(ext)s")
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            # YouTube n-challenge requires a JS runtime (node) + the EJS solver
            # (yt-dlp-ejs package). Without these, all video formats are skipped.
            'js_runtimes': {'node': {}},
            # The web client + login cookies passes the bot check; the default
            # (visionos) returns LOGIN_REQUIRED even with valid cookies.
            'extractor_args': {'youtube': {'player_client': ['web']}},
        }

        # YouTube anti-bot infrastructure: Selenium-harvested cookies.txt first
        # (shared by all workers), then explicit config, then browser fallbacks.
        from browser_session import ensure_cookies

        cookie_strategies: list = []
        try:
            refresh_h = float(self.config.get("cookie_refresh_hours", 12))
            harvested = ensure_cookies(max_age_hours=refresh_h)
            if harvested:
                cookie_strategies.append(("file", str(harvested)))
        except Exception as e:
            logger.warning(f"Cookie harvest unavailable: {e}")

        cookies_file = self.config.get("ytdlp_cookies_file")
        if cookies_file and Path(cookies_file).exists():
            cookie_strategies.append(("file", cookies_file))
        cookies_browser = self.config.get("ytdlp_cookies_browser")
        if cookies_browser:
            cookie_strategies.append(("browser", cookies_browser))
        cookie_strategies.extend([None, ("browser", "chrome"), ("browser", "edge"), ("browser", "firefox")])

        # Attempt list: each cookie strategy with the web client (proven to pass
        # the bot check), then alternative player clients as a last resort.
        attempts: list = [(cs, None) for cs in cookie_strategies]
        best_cookies = cookie_strategies[0] if cookie_strategies else None
        for client in ("tv", "android", "ios", "mweb"):
            attempts.append((best_cookies, client))

        loop = asyncio.get_event_loop()
        for strategy, player_client in attempts:
            opts = dict(ydl_opts)
            if strategy:
                kind, value = strategy
                if kind == "file":
                    opts['cookiefile'] = value
                else:
                    opts['cookiesfrombrowser'] = (value,)
            if player_client:
                opts['extractor_args'] = {"youtube": {"player_client": [player_client]}}
                # Alternative clients expose different format lists - be permissive
                opts['format'] = 'bestvideo+bestaudio/best'
            label = f"cookies from {strategy[0]}: {strategy[1]}" if strategy else "no cookies"
            if player_client:
                label += f" (player client: {player_client})"
            logger.info(f"[{task_id}] Trying download with {label}")
            try:
                def download(opts=opts):
                    if YoutubeDL is None:
                        raise RuntimeError("yt-dlp not installed")
                    with YoutubeDL(opts) as ydl:  # type: ignore[misc]
                        info = ydl.extract_info(video_url, download=True)
                        return ydl.prepare_filename(info)

                video_path = await loop.run_in_executor(None, download)
                if Path(video_path).exists():
                    return video_path
            except Exception as e:
                err = str(e)
                logger.error(f"Download failed: {err}")
                low = err.lower()
                if any(k in low for k in ("sign in to confirm", "cookie", "not a bot", "dpapi",
                                          "decrypt", "reload", "confirm you", "format is not available")):
                    continue  # try next strategy
                break

        return None

    async def _find_highlights(self, video_path: str, task_id: str, category: Optional[str] = None) -> list:
        """Find highlights: Whisper transcript -> Ollama LLM pick -> heuristic fallback."""
        try:
            highlights = await self._find_highlights_ai(video_path, task_id, category)
            if highlights:
                return highlights
        except Exception as e:
            logger.warning(f"[{task_id}] AI highlight detection failed, using heuristic: {e}")
        return await self._find_highlights_heuristic(video_path)

    def _transcribe(self, video_path: str) -> dict:
        """Transcribe audio with Whisper (word timestamps). Result is cached per video path."""
        cache = getattr(self, "_transcript_cache", None)
        if cache is None:
            cache = self._transcript_cache = {}
        if video_path in cache:
            return cache[video_path]

        import whisper
        model_name = self.config.get("whisper_model", "base")
        model = getattr(self, "_whisper_model", None)
        if model is None:
            model = self._whisper_model = whisper.load_model(model_name)
        result = model.transcribe(video_path, word_timestamps=True)
        if not isinstance(result, dict):
            result = {}
        cache[video_path] = result
        return result

    def _load_instructions(self, category: Optional[str] = None) -> str:
        """Load category-specific LLM instructions from instructions/<category>.md,
        falling back to instructions/default.md then editing_instructions.md."""
        candidates = []
        if category:
            candidates.append(Path("instructions") / f"{self._sanitize_filename(category)}.md")
        candidates.append(Path("instructions") / "default.md")
        candidates.append(Path("editing_instructions.md"))
        for path in candidates:
            if path.exists():
                logger.info(f"Using editing instructions: {path}")
                return path.read_text(encoding="utf-8")
        return ('Pick the most engaging 30-60 second segment. Respond with JSON: '
                '{"clip_start": float, "clip_end": float, "title": str}')

    # Category -> render style, per editing_styles/index.md routing matrix.
    # config.json "edit_styles" overrides these per category.
    _CATEGORY_STYLE_MAP = {
        "gaming": "hormozi",
        "high_views": "hormozi",
        "memes_funny": "hormozi",
        "podcasts": "podcast",
        "tech_news": "faceless",
        "war_geopolitical": "faceless",
        "sports": "gameplay",
        "ufc": "gameplay",
        "baby_rhymes": "kids",
        "anime": "anime",
        "anime_recap": "anime",
        "movie": "movie",
        "movies": "movie",
        "movie_recap": "movie",
        "film": "movie",
    }

    def _resolve_style(self, category: Optional[str] = None) -> str:
        """Resolve the render style for a category.

        Priority: config.json edit_styles[category] > edit_styles["default"]
        > _CATEGORY_STYLE_MAP > "subtitles".
        """
        edit_styles = self.config.get("edit_styles", {})
        if category and category in edit_styles:
            return edit_styles[category]
        if "default" in edit_styles:
            return edit_styles["default"]
        return self._CATEGORY_STYLE_MAP.get(category or "", "subtitles")

    def _ask_llm(self, prompt: str) -> dict:
        """Call Ollama /api/generate and parse the JSON object from the response."""
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
        # Extract the first JSON array or object even if the model added stray text
        arr_start, arr_end = text.find("["), text.rfind("]")
        obj_start, obj_end = text.find("{"), text.rfind("}")
        if arr_start != -1 and arr_end != -1 and (obj_start == -1 or arr_start < obj_start):
            return json.loads(text[arr_start:arr_end + 1])
        if obj_start == -1 or obj_end == -1:
            raise ValueError(f"LLM returned no JSON: {text[:200]}")
        return json.loads(text[obj_start:obj_end + 1])

    async def _find_highlights_ai(self, video_path: str, task_id: str, category: Optional[str] = None) -> list:
        """Transcribe with Whisper, then ask the LLM (category instructions) for the best clip."""
        loop = asyncio.get_event_loop()

        result = await loop.run_in_executor(None, self._transcribe, video_path)
        segments = result.get("segments") or []
        if not segments:
            logger.warning(f"[{task_id}] Whisper returned no segments")
            return []

        duration = segments[-1].get("end", 0)
        transcript = "\n".join(
            f"[{s['start']:.1f}] {s['text'].strip()}" for s in segments
        )

        instructions = self._load_instructions(category)

        max_clips = int(self.config.get("max_clips_per_video", 5))
        prompt = (
            f"{instructions}\n\n"
            f"Select up to {max_clips} of the best segments - the most engaging, "
            f"high-energy, logically complete moments that each stand on their own. "
            f"Respond with a JSON array of objects: "
            f'[{{"clip_start": float, "clip_end": float, "title": str, "reason": str}}, ...]. '
            f"If only one segment is worth clipping, return an array with a single object.\n\n"
            f"TRANSCRIPT (lines are [seconds] text):\n{transcript}\n"
        )
        data = await loop.run_in_executor(None, self._ask_llm, prompt)

        # Accept either a single object or a list of objects
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError(f"LLM returned unexpected type: {type(data)}")

        highlights = []
        for item in data[:max_clips]:
            if not isinstance(item, dict):
                continue
            try:
                clip_start = max(0.0, float(item.get("clip_start", 0)))
                clip_end = min(float(duration), float(item.get("clip_end", 60)))
            except (TypeError, ValueError):
                continue
            # Enforce 15-90s window per editing_instructions.md
            if clip_end - clip_start < 15:
                clip_end = min(float(duration), clip_start + 30)
            if clip_end - clip_start > 90:
                clip_end = clip_start + 60
            if clip_end <= clip_start:
                continue
            title = self._sanitize_filename(str(item.get("title", "highlight"))) or "highlight"
            highlights.append({"start": clip_start, "end": clip_end, "title": title})
            logger.info(f"[{task_id}] LLM selected clip {clip_start:.1f}s-{clip_end:.1f}s: {title} ({item.get('reason', '')})")

        return highlights

    async def _find_highlights_heuristic(self, video_path: str) -> list:
        """Fallback: split the video into <=60s segments."""
        try:
            # Get video duration
            cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            duration = float(stdout.decode().strip()) if stdout else 0
            
            # Simple heuristic: create 60-second clips, capped at max_clips_per_video
            highlights = []
            clip_duration = min(60, duration)
            max_clips = int(self.config.get("max_clips_per_video", 5))
            num_clips = min(max_clips, max(1, int(duration / clip_duration)))
            
            for i in range(num_clips):
                start = i * clip_duration
                end = min(start + clip_duration, duration)
                highlights.append({
                    "start": start,
                    "end": end,
                    "title": f"highlight_{i+1}"
                })
            
            return highlights
        except Exception as e:
            logger.error(f"Heuristic highlight detection failed: {e}")
            return [{"start": 0, "end": 60, "title": "default_clip"}]

    async def _create_clip(
        self, 
        video_path: str, 
        start: float, 
        end: float,
        task_id: str,
        title: str,
        category: Optional[str] = None,
        channel_name: Optional[str] = None
    ) -> Optional[str]:
        """Create a single clip from video segment."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_category = self._sanitize_filename(category or "uncategorized")
        safe_channel = self._sanitize_filename(channel_name or "unknown_channel")
        safe_title = self._sanitize_filename(title)
        
        output_dir = self.base_clips_dir / safe_category / safe_channel / date_str
        output_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{task_id}_{safe_title}_{int(start)}_{int(end)}.mp4"
        output_path = output_dir / filename

        # Edit style resolved via editing_styles/index.md routing (config.json overrides)
        style = self._resolve_style(category)

        try:
            result = await self.edit_video_clip(
                video_path=video_path,
                clip_start=start,
                clip_end=end,
                output_path=str(output_path),
                aspect_ratio="9:16",  # Default to vertical for Shorts
                task_id=task_id,
                title=title,
                style=style,
            )

            # Copyright / near-duplicate check against the local reference library.
            # Only runs when copyright_reference.json exists and has entries.
            copyright_status = "skipped"
            try:
                from copyright_check import check_clip, _load_db
                if _load_db():
                    check = await asyncio.get_event_loop().run_in_executor(
                        None, check_clip, result
                    )
                    copyright_status = check["status"]
                    if check["status"] == "flagged":
                        labels = ", ".join(m["label"] for m in check["matches"])
                        logger.warning(
                            f"[{task_id}] COPYRIGHT FLAG: {Path(result).name} "
                            f"matches reference: {labels}"
                        )
            except Exception as ce:
                logger.debug(f"[{task_id}] copyright check skipped: {ce}")

            # Save metadata to DB
            self.db.create_clip_metadata(
                task_id=task_id,
                clip_start=start,
                clip_end=end,
                duration=end - start,
                output_path=result,
                social_platform="youtube",
                title=title,
                category=category,
                channel=channel_name,
            )

            # Write paste-ready YouTube upload metadata (.txt) alongside
            try:
                from metadata_gen import write_metadata_txt
                src_url = f"https://www.youtube.com/watch?v={task_id.replace('trigger_', '')}" if task_id.startswith("trigger_") else None
                write_metadata_txt(title, category, channel_name, src_url, Path(result).name)
            except Exception as me:
                logger.debug(f"[{task_id}] metadata txt skipped: {me}")

            return result
        except Exception as e:
            logger.error(f"Clip creation failed: {e}")
            return None

    # ------------------- YouTube upload (Data API v3, OAuth) -------------------

    YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    YOUTUBE_TOKEN_FILE = "youtube_token.json"

    def _get_youtube_service(self):
        """Build an authenticated YouTube service, caching OAuth tokens locally.

        First run opens a browser consent flow; afterwards the cached
        refresh token in youtube_token.json is reused silently.
        """
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        yt_cfg = self.config.get("upload_connectors", {}).get("youtube", {})
        token_path = Path(self.YOUTUBE_TOKEN_FILE)
        creds = None

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), self.YOUTUBE_SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                client_config = {
                    "installed": {
                        "client_id": yt_cfg["client_id"],
                        "client_secret": yt_cfg["client_secret"],
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                }
                flow = InstalledAppFlow.from_client_config(client_config, self.YOUTUBE_SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json(), encoding="utf-8")

        return build("youtube", "v3", credentials=creds)

    def _upload_one_clip(self, clip_path: str, title: str, description: str, privacy: str) -> dict:
        """Blocking upload of a single clip via the YouTube Data API."""
        from googleapiclient.http import MediaFileUpload

        youtube = self._get_youtube_service()
        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "categoryId": "22",  # People & Blogs
            },
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        }
        media = MediaFileUpload(clip_path, mimetype="video/mp4", resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"Upload {os.path.basename(clip_path)}: {int(status.progress() * 100)}%")
        return response

    async def _upload_clips(self, clip_paths: list, task_id: str, category: Optional[str] = None, channel_name: Optional[str] = None) -> list:
        """Upload clips to YouTube (Data API v3). Falls back to local-only on failure.

        Set "uploads_enabled": true in config.json to actually upload. Default is
        false - clips are saved locally for manual upload.
        """
        results = []

        # Master switch: uploads disabled by default (clips saved locally)
        if not self.config.get("uploads_enabled", False):
            logger.info(f"[{task_id}] Uploads disabled - clips saved locally")
            return [{"platform": "youtube", "status": "saved_locally", "clip_path": p} for p in clip_paths]

        connectors = self.config.get("upload_connectors", {})
        youtube_config = connectors.get("youtube", {})

        # Check if YouTube connector is configured
        if not youtube_config or any(str(v).startswith("YOUR_") for v in youtube_config.values()):
            logger.info("YouTube connector not configured, skipping upload")
            return [{"platform": "youtube", "status": "skipped", "reason": "not_configured"}]

        privacy = str(self.config.get("youtube_privacy", "private"))  # safe default
        loop = asyncio.get_event_loop()

        for clip_path in clip_paths:
            title = Path(clip_path).stem
            description = f"Clip from {channel_name or 'channel'} ({category or 'general'}) - auto-clipped"
            try:
                response = await loop.run_in_executor(
                    None, self._upload_one_clip, clip_path, title, description, privacy
                )
                video_id = response.get("id", "")
                results.append({
                    "platform": "youtube",
                    "status": "uploaded",
                    "clip_path": clip_path,
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "privacy": privacy,
                })
                logger.info(f"[{task_id}] Uploaded {clip_path} -> https://www.youtube.com/watch?v={video_id}")
            except Exception as e:
                logger.error(f"[{task_id}] YouTube upload failed for {clip_path}: {e}")
                results.append({
                    "platform": "youtube",
                    "status": "upload_failed",
                    "clip_path": clip_path,
                    "error": str(e),
                    "message": "Clip saved locally, manual upload required",
                })

        return results