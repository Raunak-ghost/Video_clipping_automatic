"""APScheduler integration for periodic task triggers."""

import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

try:
    from .trigger_engine import check_for_new_videos
except ImportError:
    from trigger_engine import check_for_new_videos

logger = logging.getLogger(__name__)


class Scheduler:
    """Wrapper for APScheduler to manage periodic triggers."""
    
    def __init__(self, app=None):
        self.scheduler = AsyncIOScheduler()
        self.app = app
    
    def start(self, run_immediately: bool = True):
        """Start the scheduler with cron/interval triggers."""
        try:
            # Run channel processing cycle every 30 minutes
            self.scheduler.add_job(
                self._run_processing_cycle,
                IntervalTrigger(minutes=30),
                id="processing_cycle",
                name="Check channels for new videos every 30 minutes",
                replace_existing=True,
            )
            
            # Daily maintenance tasks at midnight
            self.scheduler.add_job(
                self._run_daily_tasks,
                CronTrigger(hour=0, minute=0),
                id="daily_tasks",
                name="Run daily maintenance tasks",
                replace_existing=True,
            )
            
            self.scheduler.start()
            logger.info("APScheduler started successfully (checking channels every 30 minutes)")
            
            if run_immediately:
                logger.info("Triggering initial channel check in background...")
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(self._run_processing_cycle())
                except Exception as loop_err:
                    logger.debug(f"Could not queue immediate check: {loop_err}")
            
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            raise
    
    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        logger.info("APScheduler stopped")
    
    def _run_daily_tasks(self):
        """Daily maintenance: delete downloaded source videos older than 7 days."""
        import time
        from pathlib import Path

        logger.info("Running daily tasks")
        max_age_seconds = 7 * 24 * 3600
        now = time.time()
        removed = 0
        for folder in (Path("downloads"),):
            if not folder.exists():
                continue
            for f in folder.iterdir():
                try:
                    if f.is_file() and now - f.stat().st_mtime > max_age_seconds:
                        f.unlink()
                        removed += 1
                except Exception as e:
                    logger.warning(f"Could not remove {f}: {e}")
        logger.info(f"Daily cleanup complete: removed {removed} old download(s)")
    
    async def _run_processing_cycle(self):
        """Run a processing cycle - check channels for new videos and queue them."""
        logger.info("Running processing cycle")
        try:
            # check_for_new_videos is sync (uses asyncio.run internally), so run it
            # in a worker thread to avoid blocking the scheduler's event loop.
            await asyncio.to_thread(check_for_new_videos)
        except Exception as e:
            logger.error(f"Processing cycle failed: {e}")
    
    def _check_webhooks(self):
        """Check for new webhooks/events."""
        logger.info("Checking for new webhooks")
        # This would check for new webhook submissions