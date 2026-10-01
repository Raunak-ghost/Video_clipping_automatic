import time
import json
import logging
import os
import schedule
import asyncio
from yt_dlp import YoutubeDL
try:
    from .pipeline import Pipeline
    from .database import init_db
    from .tasks import TaskManager
except ImportError:
    from pipeline import Pipeline
    from database import init_db
    from tasks import TaskManager

logger = logging.getLogger(__name__)


def _load_triggers_enabled():
    """Read triggers_enabled from config.json (defaults to False)."""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return bool(json.load(f).get("triggers_enabled", False))
    except Exception:
        return False


TRIGGERS_ENABLED = _load_triggers_enabled()

CHANNELS_FILE = "channels.txt"

def load_target_channels():
    """Load channels from channels.txt.

    Format (one per line):  category | channel name | channel_id
    Empty lines and lines starting with # are ignored.
    """
    categories = {}
    if os.path.exists(CHANNELS_FILE):
        try:
            with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) != 3:
                        logger.warning("Skipping malformed line: %s", line)
                        continue
                    category, name, channel_id = parts
                    categories.setdefault(category, {})[name] = channel_id
        except Exception as e:
            logger.error("Error loading channels file: %s", e)
    return categories

# Function to check if a video is long-format (> 3 minutes)
def is_long_format(video_url):
    ydl_opts = {'quiet': True, 'noplaylist': True, 'extract_flat': False}
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            duration = info.get('duration', 0) or 0
            if duration and duration > 180:
                return True
            return False
    except Exception as e:
        logger.error("Error checking duration for %s: %s", video_url, e)
        return False

# Function to execute Phase 1 of our pipeline asynchronously
async def run_phase1_ingestion(video_url, video_id, category=None, channel_name=None):
    db = init_db()
    task_id = f"trigger_{video_id}"

    if not db.task_exists(task_id):
        db.create_task(task_id)

    logger.info("Starting full pipeline for task %s: %s", task_id, video_url)
    queued_to_celery = False
    try:
        from tasks import celery_app
        inspector = celery_app.control.inspect(timeout=1.0)
        active_workers = inspector.ping() if inspector else None
        if active_workers:
            celery_id = TaskManager(db=db).queue_video_processing(task_id, video_url, category=category)
            logger.info("Task %s queued to Celery worker (id: %s).", task_id, celery_id)
            queued_to_celery = True
    except Exception as e:
        logger.warning("Celery check skipped: %s", e)

    if not queued_to_celery:
        logger.info("No active Celery worker found. Processing video directly via Pipeline...")
        try:
            pipeline = Pipeline(db=db)
            result = await pipeline.process_video(video_url, task_id=task_id, category=category, channel_name=channel_name)
            logger.info("Task %s processing result: %s", task_id, result.get('status'))
        except Exception as e:
            logger.error("Direct pipeline processing failed for %s: %s", task_id, e)
            db.update_task_status(task_id, "failed")

def _social_credentials_ready():
    """True when the youtube connector is filled in.

    Twitter and TikTok are skipped for now (clips are saved locally for
    manual upload), so their YOUR_* placeholders do NOT block processing.
    """
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            connectors = json.load(f).get("upload_connectors", {})
    except Exception:
        return False
    youtube = connectors.get("youtube", {})
    for value in youtube.values():
        if not value or str(value).startswith("YOUR_"):
            return False
    return True

async def check_for_new_videos_async():
    if not TRIGGERS_ENABLED:
        logger.info('Triggers disabled: set "triggers_enabled": true in config.json to enable.')
        return
    if not _social_credentials_ready():
        logger.info('Waiting: fill in the "youtube" connector in config.json upload_connectors before processing starts.')
        logger.info('(Twitter/TikTok are skipped - clips are saved locally for manual upload.)')
        return
    logger.info("Checking target channels for new uploads...")
    db = init_db()
    seen_videos = db.get_seen_videos()
    categories = load_target_channels()

    for category, channels in categories.items():
        for name, channel_id in channels.items():
            channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"
            ydl_opts = {'quiet': True, 'extract_flat': True, 'playlistend': 5}
            try:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(channel_url, download=False)
            except Exception as e:
                logger.error("[%s] [%s] Error listing channel: %s", category, name, e)
                continue
            
            for entry in info.get('entries') or []:
                video_id = entry.get('id')
                if not video_id:
                    continue
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                
                if video_id not in seen_videos:
                    logger.info("[%s] [%s] New video detected: %s", category, name, entry.get('title') or 'untitled')
                    
                    if is_long_format(video_url):
                        logger.info("[%s] [%s] Verified as long-format. Sending to clipping pipeline: %s", category, name, video_url)
                        
                        await run_phase1_ingestion(video_url, video_id, category=category, channel_name=name)
                        
                        db.mark_video_seen(video_id, category=category, channel_name=name)
                        seen_videos.add(video_id)
                    else:
                        logger.info("[%s] [%s] Skipped: Video is too short (likely a YouTube Short).", category, name)
                        db.mark_video_seen(video_id, category=category, channel_name=name)
                        seen_videos.add(video_id)

def check_for_new_videos():
    """Synchronous wrapper for scheduler."""
    asyncio.run(check_for_new_videos_async())

if TRIGGERS_ENABLED:
    schedule.every(15).minutes.do(check_for_new_videos)

if __name__ == "__main__":
    if not TRIGGERS_ENABLED:
        logger.info('Trigger Engine is DISABLED - set "triggers_enabled": true in config.json to enable.')
        logger.info('Edit config.json, set "triggers_enabled": true, then restart.')
    else:
        logger.info("Trigger Engine Started. Monitoring channels...")
        check_for_new_videos()

        while True:
            schedule.run_pending()
            time.sleep(1)
