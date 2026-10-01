# Pure Python Architecture - Video Clipping Pipeline

This project replaces n8n with a pure Python architecture for video clipping and processing.

## Architecture Overview

The system consists of the following components:

### 1. Scheduling ➔ APScheduler / Cron
- Triggers execution on a loop using APScheduler
- Daily triggers at midnight
- Processing cycles every 6 hours
- Hourly webhook checks

### 2. Webhooks ➔ FastAPI / Flask
- Receives webhooks and events via `/webhook` endpoint
- Validates and queues events for background processing
- Health check endpoints available

### 3. Background Tasks ➔ Celery / Redis Queue
- Manages background video processing tasks
- Prevents server crashes by offloading work
- Task queue with Redis broker and backend
- Tasks: process_video, check_webhooks, cleanup

### 4. Data Storage ➔ SQLite / PostgreSQL
- Stores task states, logs, and clip metadata
- SQLite for simple deployments (built-in)
- PostgreSQL for production scale
- Tables: tasks, logs, clip_metadata, webhook_events

### 5. Main Execution Pipeline
```
yt-dlp ➔ Whisper ➔ vLLM ➔ FFmpeg ➔ Social APIs
```

#### Pipeline Steps:
1. **Download** - yt-dlp downloads the video from URL
2. **Transcribe** - Whisper transcribes audio to text
3. **Generate** - vLLM processes transcription for clip generation
4. **Edit** - FFmpeg trims/edits video based on LLM output
5. **Publish** - Social APIs (Twitter, YouTube, TikTok) publish the clip

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd video-clipping

# Install dependencies
pip install -r requirements.txt

# Install system dependencies
# - ffmpeg must be installed on your system
# - Redis server must be running

# Start Redis
redis-server

# Initialize the database
python -c "from video_clipping.database import Database; db = Database(); db.close()"

# Start the FastAPI server
uvicorn api:app --reload

# Start Celery worker
celery -A tasks worker --loglevel=info

# Start the scheduler (from main.py)
python -c "from video_clipping.main import main; main()"
```

## Usage

### API Endpoints

- `GET /` - Root endpoint
- `GET /health` - Health check
- `POST /webhook` - Receive webhook events
- `POST /events` - Receive general events
- `GET /tasks` - List pending tasks
- `GET /tasks/{task_id}` - Get task status

### Celery Tasks

- `process_video_task(task_id, video_url)` - Full pipeline processing
- `check_webhooks_task()` - Check for new webhooks
- `cleanup_task()` - Cleanup old tasks and logs

### Scheduler

The APScheduler is automatically started with `main.py` and provides:
- Daily tasks at midnight
- Processing cycles every 6 hours
- Hourly webhook checks

## Configuration

### Environment Variables (.env)
```
REDIS_URL=redis://localhost:6379/0
DATABASE_PATH=video_clipping.db
VLLM_ENDPOINT=http://localhost:8000/v1
SOCIAL_API_KEYS=twitter=,youtube=,tiktok=
```

### Database
- Default: SQLite at `video_clipping.db`
- To use PostgreSQL, set `DATABASE_URL` environment variable and update `database.py`

## Project Structure

```
video_clipping/
├── __init__.py          # Package init
├── main.py              # Main entry point
├── scheduler.py         # APScheduler integration
├── api.py               # FastAPI webhook receiver
├── database.py          # SQLite/PostgreSQL storage
├── pipeline.py          # yt-dlp → Whisper → vLLM → FFmpeg → Social APIs
├── tasks.py             # Celery background tasks
├── requirements.txt     # Python dependencies
└── README.md            # This file
```

## License

MIT License - feel free to use and modify for your needs.