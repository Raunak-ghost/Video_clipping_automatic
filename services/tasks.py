"""Celery tasks for managing background video processing tasks."""

import asyncio
import logging
from typing import Optional
from celery import Celery

try:
    from .database import Database
except ImportError:  # allow running as a flat script
    from database import Database

logger = logging.getLogger(__name__)


# Celery application configuration
celery_app = Celery(
    "video_clipping",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
)

# Update Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    task_soft_time_limit=280,  # 4.5 minutes
)


def _get_db() -> Database:
    """Create a fresh Database connection for task execution."""
    return Database()


@celery_app.task(
    name="video_clipping.process_video_task",
    bind=True,
    soft_time_limit=280,
    time_limit=300,
    max_retries=3,
    default_retry_delay=60,
)
def process_video_task(self, task_id: str, video_url: str, **kwargs):
    """Celery task to process a video through the full pipeline."""
    logger.info(f"Starting Celery task {task_id} for video {video_url}")
    db = _get_db()

    try:
        # Update task status to processing
        db.update_task_status(task_id, "processing")

        # Initialize pipeline
        try:
            from .pipeline import Pipeline
        except ImportError:  # allow running as a flat script
            from pipeline import Pipeline
        pipeline = Pipeline(db=db)

        # Run the full pipeline
        result = asyncio.run(
            pipeline.process_video(video_url, task_id=task_id)
        )

        logger.info(f"Celery task {task_id} completed: {result}")
        return result

    except Exception as e:
        logger.error(f"Celery task {task_id} failed: {e}")
        db.update_task_status(task_id, "failed")
        return {"status": "failed", "task_id": task_id, "error": str(e)}


@celery_app.task(bind=True)
def check_webhooks_task(self, **kwargs):
    """Celery task to check for new webhooks."""
    logger.info("Checking for new webhooks")
    # This would check for new webhook submissions and queue them
    return {"status": "checked", "message": "Webhook check completed"}


@celery_app.task(bind=True)
def cleanup_task(self, **kwargs):
    """Celery task for cleanup (old tasks, logs, etc.)."""
    logger.info("Running cleanup task")
    # Cleanup old tasks, logs, etc.
    return {"status": "cleaned", "message": "Cleanup completed"}


class TaskManager:
    """Manager for Celery tasks related to video processing."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    def queue_video_processing(self, task_id: str, video_url: str, category: Optional[str] = None) -> str:
        """Queue a video processing task, routed to a per-category queue.

        Workers pick their category with:  celery -A tasks worker -Q category_gaming
        Tasks without a category go to the default 'celery' queue.
        """
        queue = f"category_{category}" if category else "celery"
        result = celery_app.send_task(
            "video_clipping.process_video_task",
            args=[task_id, video_url],
            queue=queue,
        )
        logger.info(f"Queued video processing task {task_id} to queue '{queue}', Celery ID: {result.id}")
        return result.id

    def get_task_result(self, task_id: str) -> dict:
        """Get the result of a Celery task."""
        try:
            # Use AsyncResult from celery.result
            from celery.result import AsyncResult
            result = AsyncResult(task_id, app=celery_app)
            return {
                "task_id": task_id,
                "status": result.status,
                "result": result.result if result.result else None,
            }
        except Exception as e:
            logger.error(f"Failed to get task result: {e}")
            return {"task_id": task_id, "status": "error", "error": str(e)}