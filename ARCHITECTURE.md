# Video Clipping Pipeline - Architecture Document

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        VIDEO CLIPPING PIPELINE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐  │
│  │  Channels    │    │   Trigger    │    │   Pipeline   │    │  Clips   │  │
│  │  (channels.  │───▶│   Engine     │───▶│  (process_   │───▶│  (clips/ │  │
│  │   txt)       │    │  (scheduler) │    │   video)     │    │  upload) │  │
│  └──────────────┘    └──────────────┘    └──────────────┘    └──────────┘  │
│        ▲                   │                    │                    │       │
│        │                   │                    ▼                    │       │
│        │            ┌──────────────┐    ┌──────────────┐            │       │
│        │            │   Database   │◀───│   Celery     │            │       │
│        │            │  (SQLite)    │    │   Workers    │            │       │
│        │            └──────────────┘    └──────────────┘            │       │
│        │                   ▲                    ▲                    │       │
│        └───────────────────┴────────────────────┴────────────────────┘       │
│                                    │                                         │
│                            ┌───────┴───────┐                                 │
│                            │   FastAPI     │                                 │
│                            │   (api.py)    │                                 │
│                            │  - Admin UI   │                                 │
│                            │  - Webhooks   │                                 │
│                            │  - Edit API   │                                 │
│                            └───────────────┘                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## File Inventory & Responsibilities

| File | Role | Status |
|------|------|--------|
| `main.py` | Entry point - starts FastAPI + Scheduler | ✅ Working |
| `api.py` | FastAPI app - REST API, Admin UI, Webhooks | ✅ Working (after pipeline fix) |
| `database.py` | SQLite wrapper with WAL mode | ✅ Fixed (seen_videos methods) |
| `pipeline.py` | **Core processing logic** | ✅ **Rewritten** |
| `trigger_engine.py` | Channel monitoring + trigger logic | ✅ Fixed (async, DB integration) |
| `scheduler.py` | APScheduler wrapper (30min intervals) | ✅ Working |
| `tasks.py` | Celery tasks + TaskManager | ✅ Working (after pipeline fix) |
| `run_one.py` | Direct execution bypassing Celery | ✅ Working (after pipeline fix) |
| `config.json` | Configuration (connectors, channels) | External |

---

## Data Flow

```
1. SCHEDULER (APScheduler, every 30 min)
   │
   ▼
2. trigger_engine.check_for_new_videos()
   │  - Loads channels from channels.txt
   │  - For each channel: yt-dlp lists recent videos
   │  - Checks DB.seen_videos for new ones
   │  - Filters: duration > 3 min (not Shorts)
   │
   ▼
3. For each new video:
   │  - Creates task in DB (task_id = "trigger_<video_id>")
   │  - Tries Celery queue (if workers available)
   │  - Falls back to direct Pipeline.process_video()
   │
   ▼
4. PIPELINE.process_video() [async]
   │  - Downloads video (yt-dlp)
   │  - Finds highlights (heuristic/AI)
   │  - Creates 9:16 clips (FFmpeg AMF)
   │  - Saves clip metadata to DB
   │  - Uploads to YouTube (if configured)
   │
   ▼
5. DB updated: task status = completed, clip_path set
   │
   ▼
6. ADMIN UI (FastAPI /admin) shows task + clip
   │  - Manual edit: /videos/{task_id}/edit
   │  - Pipeline.edit_video_clip() for custom cuts
```

---

## Fixed Issues Summary

### 1. `pipeline.py` - **COMPLETE REWRITE** (Was broken)

**Before:** Simple FFmpeg wrapper class expecting `config` dict, only had `process_clip()` and `publish_clip()`.
**Callers expected:** `Pipeline(db=db).process_video()` and `Pipeline(db=db).edit_video_clip()` returning dicts with status.

**Fixed:** New `Pipeline` class with:
- `__init__(db)` - accepts Database instance
- `process_video(video_url, task_id, category, channel_name)` → `{"status": "completed/failed", ...}`
- `edit_video_clip(video_path, clip_start, clip_end, output_path, aspect_ratio, task_id, title)` → output path
- Full flow: download → highlights → clip → metadata → upload
- Hardware acceleration (AMF) with libx264 fallback
- 9:16 vertical conversion for Shorts

### 2. `trigger_engine.py` - **MAJOR FIXES**

| Issue | Before | After |
|-------|--------|-------|
| Event loop | `asyncio.run()` inside sync loop (creates new loop each video) | `check_for_new_videos_async()` + sync wrapper |
| Seen videos | JSON file (`seen_videos.json`) with O(n) list lookup | SQLite `seen_videos` table with O(1) set |
| Logging | Mixed `print()` and `logger` | All `logger` |
| Channel URL | `youtube.com/channel/{id}/videos` | Same (works with yt-dlp) |
| DB usage | New `init_db()` per video | Single DB instance per check cycle |

### 3. `database.py` - **FIXED METHOD PLACEMENT**

**Bug:** `video_seen()`, `mark_video_seen()`, `get_seen_videos()` defined **outside** `Database` class (indentation error).

**Fixed:** Moved inside class. Added `seen_videos` table:
```sql
CREATE TABLE seen_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT UNIQUE NOT NULL,
    category TEXT,
    channel_name TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

### 4. `api.py` - **WORKS NOW** (was failing due to pipeline)

Calls that now work:
- `Pipeline(db=db).edit_video_clip(...)` at line 204
- `Pipeline(db=db)` instantiation at line 198

### 5. `tasks.py` - **WORKS NOW** (was failing due to pipeline)

Calls that now work:
- `Pipeline(db=db).process_video(...)` at line 66
- `Pipeline(db=db)` instantiation at line 63

### 6. `run_one.py` - **WORKS NOW** (was failing due to pipeline)

Calls that now work:
- `Pipeline(db=db).process_video(...)` at line 22

---

## Required Dependencies

```bash
# Core
pip install fastapi uvicorn apscheduler

# Database
# sqlite3 (stdlib)

# Video processing
pip install yt-dlp

# Async task queue (optional)
pip install celery redis

# Scheduler (trigger_engine standalone)
pip install schedule
```

---

## Configuration (`config.json`)

```json
{
  "triggers_enabled": true,
  "clips_dir": "clips",
  "downloads_dir": "downloads",
  "ffmpeg_path": "ffmpeg",
  "encoder": "h264_amf",
  "admin_token": "your-admin-token",
  "upload_connectors": {
    "youtube": {
      "client_id": "YOUR_CLIENT_ID",
      "client_secret": "YOUR_CLIENT_SECRET",
      "refresh_token": "YOUR_REFRESH_TOKEN"
    }
  }
}
```

---

## Channel Format (`channels.txt`)

```
# category | channel name | channel_id
Tech | MKBHD | UCXuqSBlHAE6Xw-yeJA0Tunw
Tech | Linus Tech Tips | UCFX98CxTg8Qy2rX6eJ4KZ7A
Gaming | GameSpot | UCv9dIIDl6v0S8H-l7y9KZ9Q
```

---

## Running the System

### Option 1: Full Stack (API + Scheduler)
```bash
python main.py
# Serves on http://localhost:8001/admin
```

### Option 2: Trigger Engine Only (standalone)
```bash
python trigger_engine.py
# Runs schedule loop, checks every 15 min
```

### Option 3: Direct Processing (bypass Celery)
```bash
python run_one.py "https://youtube.com/watch?v=..." "my_task_id"
```

### Option 4: Celery Worker (for production)
```bash
celery -A tasks worker -l info
```

---

## Error Handling & Retry Logic

| Component | Retry Strategy |
|-----------|----------------|
| Celery tasks | 3 retries, 60s delay, 5min timeout |
| FFmpeg | Try AMF encoder → fallback to libx264 |
| yt-dlp | Single attempt, logs error |
| YouTube upload | Skips if connector not configured |
| Scheduler | APScheduler handles missed runs |

---

## Database Schema

```sql
-- Tasks
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress REAL DEFAULT 0.0,
    video_url TEXT,
    clip_path TEXT,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Logs
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

-- Clip Metadata
CREATE TABLE clip_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    clip_start REAL,
    clip_end REAL,
    duration REAL,
    output_path TEXT,
    social_platform TEXT,
    title TEXT,
    category TEXT,
    channel TEXT,
    posted_at TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

-- Seen Videos (NEW)
CREATE TABLE seen_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT UNIQUE NOT NULL,
    category TEXT,
    channel_name TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Webhooks
CREATE TABLE webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    source TEXT,
    payload TEXT,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed INTEGER DEFAULT 0
);
```

---

## Known Limitations / TODOs

1. **Highlight detection** - Currently simple time-based splitting. Should integrate Ollama/LLM for smart highlights.
2. **YouTube upload** - Placeholder only. Needs `google-api-python-client` implementation.
3. **Celery broker** - Requires Redis running on localhost:6379.
4. **FFmpeg hardware** - Assumes AMD AMF (`h264_amf`). Change `encoder` in config for NVIDIA (`h264_nvenc`) or Intel (`h264_qsv`).
5. **Channels.txt** - Manual maintenance. Could add API to manage via admin UI.

---

## File-by-File Error History

| File | Errors Found | Fix Applied |
|------|--------------|-------------|
| `pipeline.py` | Wrong interface, missing methods | Complete rewrite with full Pipeline class |
| `trigger_engine.py` | asyncio.run in loop, JSON file for seen_videos, mixed logging | Async refactor, DB integration, unified logging |
| `database.py` | seen_videos methods outside class | Moved inside Database class, added table |
| `api.py` | Would fail at runtime (pipeline missing methods) | Fixed by pipeline rewrite |
| `tasks.py` | Would fail at runtime (pipeline missing methods) | Fixed by pipeline rewrite |
| `run_one.py` | Would fail at runtime (pipeline missing methods) | Fixed by pipeline rewrite |
| `scheduler.py` | No errors | Clean |
| `main.py` | No errors | Clean |