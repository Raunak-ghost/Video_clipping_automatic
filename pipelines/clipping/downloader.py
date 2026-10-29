"""Video Downloader module (yt-dlp + cookie handling)."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

try:
    from yt_dlp import YoutubeDL
except ImportError:
    YoutubeDL = None

logger = logging.getLogger(__name__)


class VideoDownloader:
    """Manages video downloads via yt-dlp with multiple cookie fallback strategies."""

    def __init__(self, downloads_dir: Path, config: dict):
        self.downloads_dir = downloads_dir
        self.config = config
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    async def download(self, video_url: str, task_id: str) -> Optional[str]:
        """Download video using yt-dlp."""
        if not YoutubeDL:
            logger.error("yt-dlp is not installed")
            return None

        output_template = str(self.downloads_dir / f"{task_id}_%(title)s.%(ext)s")

        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "js_runtimes": {"node": {}},
            "extractor_args": {"youtube": {"player_client": ["web"]}},
        }

        from browser_session import ensure_cookies

        cookie_strategies = []
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

        attempts = [(cs, None) for cs in cookie_strategies]
        best_cookies = cookie_strategies[0] if cookie_strategies else None
        for client in ("tv", "android", "ios", "mweb"):
            attempts.append((best_cookies, client))

        loop = asyncio.get_event_loop()
        for strategy, player_client in attempts:
            opts = dict(ydl_opts)
            if strategy:
                kind, value = strategy
                if kind == "file":
                    opts["cookiefile"] = value
                else:
                    opts["cookiesfrombrowser"] = (value,)
            if player_client:
                opts["extractor_args"] = {"youtube": {"player_client": [player_client]}}
                opts["format"] = "bestvideo+bestaudio/best"

            try:
                def run_dl(opts=opts):
                    with YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(video_url, download=True)
                        return ydl.prepare_filename(info)

                video_path = await loop.run_in_executor(None, run_dl)
                if Path(video_path).exists():
                    return video_path
            except Exception as e:
                err = str(e).lower()
                if any(k in err for k in ("sign in to confirm", "cookie", "not a bot", "dpapi", "decrypt", "reload")):
                    continue
                break

        return None
