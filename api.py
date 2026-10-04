"""FastAPI application: webhooks, local video-database API, video editing, and admin dashboard."""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from database import init_db, close
    from pipeline import Pipeline
except ImportError:
    # Fallback for different execution contexts
    import database
    import pipeline
    init_db = database.init_db
    close = database.close
    Pipeline = pipeline.Pipeline

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent / "config.json"


def load_config() -> dict:
    """Load config.json (admin token, upload connectors, channels)."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Error loading config: {e}")
    return {}


def get_admin_token() -> str:
    """Admin token from config.json (defaults to 'admin' for local dev)."""
    return load_config().get("admin_token", "admin")


async def require_admin(request: Request) -> bool:
    """Admin-only guard. Pass ?token=... or the X-Admin-Token header."""
    token = request.headers.get("x-admin-token") or request.query_params.get("token")
    if token != get_admin_token():
        raise HTTPException(status_code=401, detail="Unauthorized: valid admin token required")
    return True


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Video Clipping Pipeline API",
        description="Webhooks, video editing, local video-database queries, and the admin dashboard",
        version="1.2.0",
    )

    # Ensure static directories exist and mount them
    clips_dir = Path("clips")
    clips_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir = Path("downloads")
    downloads_dir.mkdir(parents=True, exist_ok=True)

    app.mount("/clips", StaticFiles(directory="clips"), name="clips")
    app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")

    @app.on_event("startup")
    async def startup_event():
        try:
            from scheduler import Scheduler
            scheduler = Scheduler(app)
            scheduler.start(run_immediately=False)
            app.state.scheduler = scheduler
            logger.info("Scheduler started successfully within FastAPI event loop")
        except Exception as e:
            logger.warning(f"Could not start scheduler on startup: {e}")

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "message": "Video Clipping Pipeline API",
            "status": "running",
            "admin_dashboard": "/admin",
            "videos_api": "/videos (admin token required)",
            "edit_api": "/videos/edit (admin token required)",
        }

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "service": "video-clipping-api"}

    @app.post("/webhook")
    async def receive_webhook(request: Request):
        """Receive webhook events from various sources."""
        try:
            payload = await request.json()
            logger.info(f"Received webhook: {payload}")

            if not payload:
                raise HTTPException(status_code=400, detail="Empty payload")

            event_type = payload.get("event_type", "unknown")

            return JSONResponse(
                content={"status": "received", "event_type": event_type},
                status_code=200,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/events")
    async def receive_event(request: Request):
        """Receive general events for processing."""
        try:
            payload = await request.json()
            logger.info(f"Received event: {payload}")

            event_data = {
                "timestamp": payload.get("timestamp"),
                "source": payload.get("source"),
                "payload": payload,
            }

            return JSONResponse(
                content={"status": "event_queued", "event_data": event_data},
                status_code=202,
            )

        except Exception as e:
            logger.error(f"Event error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------- Video Editing API (admin only) -------------------

    @app.post("/videos/edit")
    @app.post("/videos/{task_id}/edit")
    async def edit_video(
        request: Request,
        task_id: Optional[str] = None,
        _admin: bool = Depends(require_admin),
    ):
        """Edit a video clip: frame-accurate trimming, 9:16 vertical conversion for Shorts, and platform publishing."""
        try:
            body = await request.json()
        except Exception:
            body = {}

        target_task_id = task_id or body.get("task_id")
        clip_start = float(body.get("clip_start", 0.0))
        clip_end = float(body.get("clip_end", 60.0))
        aspect_ratio = body.get("aspect_ratio", "original")  # "original", "9:16", "16:9"
        style = body.get("style", "subtitles")  # subtitles/hormozi/podcast/faceless/gameplay/corporate/blur
        title = body.get("title")
        platform = body.get("platform", "youtube").lower().strip()

        db = init_db()
        try:
            # 1. Locate source video
            source_video: Optional[Path] = None

            # Explicit path passed in body
            if body.get("video_path"):
                p = Path(body["video_path"])
                if p.exists():
                    source_video = p

            # Match task download
            if not source_video and target_task_id:
                candidates = sorted(
                    list(Path("downloads").glob(f"{target_task_id}_*.mp4"))
                    + list(Path("downloads").glob(f"{target_task_id}_*.webm")),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    source_video = candidates[0]
                else:
                    task = db.get_task(target_task_id)
                    if task and task.get("clip_path") and Path(task["clip_path"]).exists():
                        source_video = Path(task["clip_path"])

            if not source_video or not source_video.exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"Source video for task '{target_task_id}' not found in downloads/ or clips/.",
                )

            # 2. Render edited clip with Pipeline
            effective_task_id = target_task_id or f"edit_{int(clip_start)}_{int(clip_end)}"
            pipeline = Pipeline(db=db)

            clean_tag = "vertical" if aspect_ratio == "9:16" else "clip"
            output_filename = f"{effective_task_id}_{clean_tag}.mp4"
            output_path = Path("clips") / output_filename

            edited_clip = await pipeline.edit_video_clip(
                video_path=str(source_video),
                clip_start=clip_start,
                clip_end=clip_end,
                output_path=str(output_path),
                aspect_ratio=aspect_ratio,
                task_id=effective_task_id,
                title=title,
                style=style,
            )

            # 3. Copy to destination platform folder
            platform_dir = Path("clips") / platform
            platform_dir.mkdir(parents=True, exist_ok=True)
            platform_clip_dest = platform_dir / output_filename
            shutil.copy2(edited_clip, platform_clip_dest)

            duration = max(1.0, clip_end - clip_start)

            # 4. Save metadata to DB
            clip_meta_id = db.create_clip_metadata(
                task_id=effective_task_id,
                clip_start=clip_start,
                clip_end=clip_end,
                duration=duration,
                output_path=str(platform_clip_dest),
                social_platform=platform,
            )

            # Update task status if it exists
            if target_task_id and db.task_exists(target_task_id):
                db.update_task_status(
                    target_task_id,
                    "completed",
                    clip_path=str(platform_clip_dest),
                )

            return {
                "status": "success",
                "task_id": effective_task_id,
                "title": title or output_filename,
                "clip_path": str(platform_clip_dest),
                "url": f"/clips/{platform}/{output_filename}",
                "clip_start": clip_start,
                "clip_end": clip_end,
                "duration": duration,
                "aspect_ratio": aspect_ratio,
                "platform": platform,
                "upload_status": "ready_for_upload" if platform == "youtube" else "saved_for_manual_upload",
                "metadata_id": clip_meta_id,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Video editing error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            close(db)

    # ------------------- local video database API (admin only) -------------------

    @app.get("/videos")
    async def list_videos(
        status: str = Query(None, description="Filter: pending/processing/completed/failed"),
        limit: int = Query(100, le=500),
        _admin: bool = Depends(require_admin),
    ):
        """List all videos/tasks stored in the database."""
        db = init_db()
        try:
            videos = db.list_tasks(status=status, limit=limit)
            return {"count": len(videos), "stats": db.count_by_status(), "videos": videos}
        finally:
            close(db)

    @app.get("/videos/{task_id}")
    async def get_video(task_id: str, _admin: bool = Depends(require_admin)):
        """Get one video/task with its clips and logs."""
        db = init_db()
        try:
            task = db.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            task["clips"] = db.get_clips(task["id"])
            task["logs"] = db.get_task_logs(task["id"])
            return task
        finally:
            close(db)

    @app.get("/tasks")
    async def list_tasks(
        status: str = Query(None),
        limit: int = Query(100, le=500),
        _admin: bool = Depends(require_admin),
    ):
        """List all pending/processing tasks (DB-backed)."""
        db = init_db()
        try:
            tasks = db.list_tasks(status=status, limit=limit)
            return {"tasks": tasks, "count": len(tasks)}
        finally:
            close(db)

    @app.get("/tasks/{task_id}")
    async def get_task_status(task_id: str, _admin: bool = Depends(require_admin)):
        """Get status of a specific task (DB-backed)."""
        db = init_db()
        try:
            task = db.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            return task
        finally:
            close(db)

    # ------------------- clip library + workers (admin only) -------------------

    @app.get("/clips")
    async def list_clip_library(_admin: bool = Depends(require_admin)):
        """Clip library grouped by category -> channel -> date (new folder structure)."""
        clips_root = Path("clips")
        tree: Dict[str, Any] = {}
        total = 0
        if clips_root.exists():
            for f in sorted(clips_root.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
                rel = f.relative_to(clips_root)
                if len(rel.parts) >= 4:
                    category, channel, date = rel.parts[0], rel.parts[1], rel.parts[2]
                elif len(rel.parts) == 2:
                    category, channel, date = rel.parts[0], "-", "-"  # legacy platform folder
                else:
                    category, channel, date = "uncategorized", "-", "-"
                url = "/clips/" + "/".join(rel.parts)
                entry = {
                    "name": f.name,
                    "url": url,
                    "size_mb": round(f.stat().st_size / 1e6, 1),
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                }
                tree.setdefault(category, {}).setdefault(channel, {}).setdefault(date, []).append(entry)
                total += 1
        return {"total": total, "tree": tree}

    @app.get("/workers")
    async def list_workers(_admin: bool = Depends(require_admin)):
        """List Celery workers (with their category queues); falls back to the local
        orchestrator as 'worker 0' when no Celery workers are running."""
        workers = []
        try:
            from tasks import celery_app
            insp = celery_app.control.inspect(timeout=1.0)
            pings = insp.ping() or {}
            active = insp.active() or {}
            queues = insp.active_queues() or {}
            stats = insp.stats() or {}
            for name in pings:
                w_queues = [q.get("name") for q in queues.get(name, [])]
                categories = [q.replace("category_", "") for q in w_queues if q.startswith("category_")]
                w_active = active.get(name, [])
                w_stats = stats.get(name) or {}
                workers.append({
                    "name": name,
                    "type": "celery",
                    "status": "online",
                    "queues": w_queues,
                    "categories": categories or ["all"],
                    "active_tasks": len(w_active),
                    "active_task_ids": [t.get("name", "?") for t in w_active][:5],
                    "concurrency": w_stats.get("pool", {}).get("max-concurrency"),
                })
        except Exception as e:
            logger.debug(f"Celery inspect failed (no workers?): {e}")

        if not workers:
            # Local fallback: the main process orchestrator acts as worker 0
            db = init_db()
            try:
                processing = db.list_tasks(status="processing", limit=10)
            finally:
                close(db)
            workers.append({
                "name": "worker-0 (local orchestrator)",
                "type": "local",
                "status": "online",
                "queues": ["local"],
                "categories": ["all"],
                "active_tasks": len(processing),
                "active_task_ids": [t.get("task_id") for t in processing],
                "concurrency": 1,
            })
        return {"count": len(workers), "workers": workers}

    # ------------------- admin dashboard (local GUI, admin only) -------------------

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_dashboard():
        """Taskbar-style admin GUI with video editing and database monitoring."""
        token = get_admin_token()
        return ADMIN_DASHBOARD_HTML.replace("__DEFAULT_ADMIN_TOKEN__", token)

    return app


ADMIN_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Video Clipping & Editing Control Center</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg: #0b0d13;
    --bar: #131722;
    --card: #181d2a;
    --card-hover: #1f2536;
    --border: #262c3d;
    --text: #e6e9ef;
    --muted: #8b93a3;
    --accent: #6366f1;
    --accent-hover: #4f46e5;
    --green: #22c55e;
    --yellow: #eab308;
    --blue: #38bdf8;
    --red: #ef4444;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }
  .taskbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 20px;
    background: var(--bar);
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 100;
    flex-wrap: wrap;
  }
  .taskbar h1 {
    font-size: 16px;
    margin: 0;
    font-weight: 700;
    letter-spacing: -0.02em;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .badge {
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 6px;
    background: rgba(99, 102, 241, 0.15);
    color: var(--accent);
    font-weight: 700;
    border: 1px solid rgba(99, 102, 241, 0.3);
  }
  .taskbar input {
    background: #0b0d13;
    border: 1px solid var(--border);
    color: var(--text);
    padding: 7px 12px;
    border-radius: 6px;
    font-size: 13px;
    width: 220px;
  }
  .taskbar button, .btn {
    background: var(--accent);
    border: 0;
    color: #fff;
    font-weight: 600;
    padding: 7px 14px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    transition: background 0.15s ease;
  }
  .taskbar button:hover, .btn:hover { background: var(--accent-hover); }
  .btn-secondary {
    background: #23293a;
    color: var(--text);
    border: 1px solid var(--border);
  }
  .btn-secondary:hover { background: #2b3347; }
  .btn-sm {
    padding: 4px 10px;
    font-size: 12px;
    border-radius: 4px;
  }
  .spacer { flex: 1; }
  .stats { display: flex; gap: 12px; padding: 16px 20px; flex-wrap: wrap; }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 18px;
    min-width: 120px;
  }
  .card .num { font-size: 22px; font-weight: 700; }
  .card .lbl { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-top: 2px; }
  
  main { padding: 0 20px 40px; }
  .table-container {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow-x: auto;
  }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 12px 14px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .05em; background: #141824; }
  tr:hover td { background: var(--card-hover); }
  .pill {
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    text-transform: capitalize;
    display: inline-block;
  }
  .pending { background: rgba(234, 179, 8, 0.15); color: var(--yellow); }
  .processing { background: rgba(56, 189, 248, 0.15); color: var(--blue); }
  .completed { background: rgba(34, 197, 94, 0.15); color: var(--green); }
  .failed { background: rgba(239, 68, 68, 0.15); color: var(--red); }
  a { color: var(--blue); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .muted { color: var(--muted); }
  .err { color: var(--red); }

  /* Modal */
  .modal-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.75);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 200;
    backdrop-filter: blur(4px);
  }
  .modal {
    background: #151924;
    border: 1px solid var(--border);
    border-radius: 12px;
    width: 90%;
    max-width: 520px;
    padding: 24px;
    box-shadow: 0 20px 40px rgba(0,0,0,0.5);
  }
  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 18px;
  }
  .modal-header h2 { margin: 0; font-size: 18px; }
  .close-btn {
    background: transparent;
    border: 0;
    color: var(--muted);
    font-size: 20px;
    cursor: pointer;
  }
  .form-group { margin-bottom: 14px; }
  .form-group label {
    display: block;
    font-size: 12px;
    font-weight: 600;
    color: var(--muted);
    margin-bottom: 6px;
    text-transform: uppercase;
  }
  .form-group input, .form-group select {
    width: 100%;
    background: #0d1017;
    border: 1px solid var(--border);
    color: var(--text);
    padding: 9px 12px;
    border-radius: 6px;
    font-size: 13px;
  }
  .row-inputs { display: flex; gap: 12px; }
  .row-inputs > div { flex: 1; }
  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    margin-top: 24px;
  }
  .toast {
    padding: 10px 14px;
    border-radius: 6px;
    font-size: 13px;
    margin-top: 14px;
    display: none;
  }
  .toast.success { background: rgba(34, 197, 94, 0.15); border: 1px solid var(--green); color: var(--green); }
  .toast.error { background: rgba(239, 68, 68, 0.15); border: 1px solid var(--red); color: var(--red); }

  /* Workers */
  .section-title {
    padding: 18px 20px 0;
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: var(--muted);
  }
  .worker-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 18px;
    min-width: 220px;
  }
  .worker-card .wname { font-weight: 700; font-size: 14px; display: flex; align-items: center; gap: 8px; }
  .worker-card .wdetail { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .dot.online { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .dot.offline { background: var(--red); }
  .queue-tag {
    display: inline-block;
    background: rgba(56, 189, 248, 0.12);
    color: var(--blue);
    border: 1px solid rgba(56, 189, 248, 0.3);
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 11px;
    margin: 2px 3px 0 0;
  }

  /* Clip library tree */
  .clip-tree { padding: 12px 20px 30px; }
  .clip-tree details {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 8px;
    padding: 8px 14px;
  }
  .clip-tree details details { background: #141824; margin: 6px 0; }
  .clip-tree summary {
    cursor: pointer;
    font-weight: 600;
    font-size: 13px;
    padding: 4px 0;
    user-select: none;
  }
  .clip-tree summary:hover { color: var(--accent); }
  .clip-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 5px 0 5px 12px;
    font-size: 12px;
    border-bottom: 1px solid var(--border);
  }
  .clip-item:last-child { border-bottom: 0; }
  .clip-item .size { color: var(--muted); font-size: 11px; }
</style>
</head>
<body>
  <div class="taskbar">
    <h1>&#127916; Video Clipping & Editing Studio</h1>
    <span class="badge">GPU AMF READY</span>
    <input id="token" type="password" placeholder="admin token">
    <button onclick="saveToken()">Save</button>
    <button onclick="refreshAll()">Refresh</button>
    <button class="btn-secondary" onclick="openNewEditModal()">+ New Custom Edit</button>
    <div class="spacer"></div>
    <span id="last" class="muted"></span>
  </div>

  <div class="stats" id="stats"></div>

  <div class="section-title">Workers</div>
  <div class="stats" id="workers">
    <div class="worker-card"><div class="wname"><span class="dot offline"></span>Loading...</div></div>
  </div>

  <main>
    <div class="section-title" style="padding-left:0">Tasks</div>
    <div class="table-container">
      <table>
        <thead><tr>
          <th>Task ID</th>
          <th>Status</th>
          <th>Progress</th>
          <th>Original Video</th>
          <th>Generated Clip</th>
          <th>Actions</th>
        </tr></thead>
        <tbody id="rows">
          <tr><td colspan="6" class="muted">Enter your admin token and press Refresh.</td></tr>
        </tbody>
      </table>
    </div>

    <div class="section-title" style="padding-left:0">Clip Library</div>
    <div class="clip-tree" id="clipTree">
      <div class="muted" style="font-size:13px">Loading clips...</div>
    </div>
  </main>

  <!-- Edit Modal -->
  <div id="editModal" class="modal-overlay">
    <div class="modal">
      <div class="modal-header">
        <h2 id="modalTitle">Edit Video Clip</h2>
        <button class="close-btn" onclick="closeEditModal()">&times;</button>
      </div>

      <div class="form-group">
        <label>Task / Video Identifier</label>
        <input id="modalTaskId" type="text" placeholder="e.g. mkbhd_run1 or custom ID">
      </div>

      <div class="row-inputs">
        <div class="form-group">
          <label>Start Second</label>
          <input id="modalClipStart" type="number" step="0.5" value="0.0" min="0">
        </div>
        <div class="form-group">
          <label>End Second</label>
          <input id="modalClipEnd" type="number" step="0.5" value="30.0" min="1">
        </div>
      </div>

      <div class="form-group">
        <label>Aspect Ratio & Format</label>
        <select id="modalAspectRatio">
          <option value="9:16">9:16 Vertical (YouTube Shorts / TikTok / Reels)</option>
          <option value="original">Original Aspect Ratio</option>
          <option value="16:9">16:9 Standard Widescreen</option>
        </select>
      </div>

      <div class="form-group">
        <label>Edit Style</label>
        <select id="modalStyle">
          <option value="subtitles">Subtitles - centered word-by-word captions (9:16)</option>
          <option value="hormozi">Hormozi - kinetic typography, big center words</option>
          <option value="podcast">Podcast - dual split-screen speakers</option>
          <option value="faceless">Faceless - blurred bg + clean lower-thirds</option>
          <option value="gameplay">Gameplay - top 60% clip / bottom 40% fill</option>
          <option value="corporate">Corporate - minimal lower-third banner</option>
          <option value="kids">Kids - big rounded colorful captions (rhymes)</option>
          <option value="anime">Anime Recap - full-screen + white bottom captions</option>
          <option value="movie">Movie Recap - full-screen + white center captions</option>
          <option value="blur">Blur - blurred background vertical (9:16)</option>
        </select>
      </div>

      <div class="form-group">
        <label>Target Platform</label>
        <select id="modalPlatform">
          <option value="youtube">YouTube (Active Online Connector)</option>
          <option value="twitter">Twitter (Saved for Manual Upload)</option>
          <option value="tiktok">TikTok (Saved for Manual Upload)</option>
        </select>
      </div>

      <div class="form-group">
        <label>Clip Title (Optional)</label>
        <input id="modalClipTitle" type="text" placeholder="e.g. Top Highlight">
      </div>

      <div id="modalToast" class="toast"></div>

      <div class="modal-actions">
        <button class="btn btn-secondary" onclick="closeEditModal()">Cancel</button>
        <button id="renderBtn" class="btn" onclick="submitVideoEdit()">&#9881; Render Edited Clip</button>
      </div>
    </div>
  </div>

<script>
const defaultToken = "__DEFAULT_ADMIN_TOKEN__";
const tokenInput = document.getElementById('token');
const storedToken = localStorage.getItem('admin_token');
tokenInput.value = (storedToken && storedToken.trim()) ? storedToken : defaultToken;
localStorage.setItem('admin_token', tokenInput.value);

function saveToken(){
  localStorage.setItem('admin_token', tokenInput.value);
  loadVideos();
}

function esc(s){
  return (s == null ? '' : s).toString().replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

async function loadVideos(){
  const t = tokenInput.value;
  try {
    const r = await fetch('/videos?limit=200', {headers:{'X-Admin-Token': t}});
    if (r.status === 401){
      document.getElementById('rows').innerHTML =
        '<tr><td colspan="6" class="err">401 Unauthorized - invalid admin token.</td></tr>';
      return;
    }
    const d = await r.json();
    const s = d.stats || {};
    document.getElementById('stats').innerHTML =
      ['completed','processing','pending','failed'].map(k =>
        `<div class="card"><div class="num">${s[k]||0}</div><div class="lbl">${k}</div></div>`
      ).join('') +
      `<div class="card"><div class="num">${d.count}</div><div class="lbl">total tasks</div></div>`;

    document.getElementById('rows').innerHTML = (d.videos || []).map(v => {
      const clipPath = v.clip_path || '';
      const clipFilename = clipPath ? clipPath.split(/[\\\\/]/).pop() : '';
      const clipUrl = clipPath ? `/${clipPath.replace(/\\\\/g, '/')}` : '';

      return `<tr>
        <td><strong>${esc(v.task_id)}</strong></td>
        <td><span class="pill ${esc(v.status)}">${esc(v.status)}</span></td>
        <td>${v.progress != null ? v.progress : 0}%</td>
        <td>${v.video_url ? `<a href="${esc(v.video_url)}" target="_blank">&#128279; Watch Source</a>` : '<span class="muted">-</span>'}</td>
        <td>
          ${clipPath ? `<a href="${esc(clipUrl)}" target="_blank">&#9654; ${esc(clipFilename)}</a>` : '<span class="muted">No clip yet</span>'}
        </td>
        <td>
          <button class="btn btn-sm" onclick="openEditModalForTask('${esc(v.task_id)}')">&#9998; Edit Clip</button>
        </td>
      </tr>`;
    }).join('') || '<tr><td colspan="6" class="muted">No tasks recorded in database yet.</td></tr>';

    document.getElementById('last').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e){
    document.getElementById('rows').innerHTML = `<tr><td colspan="6" class="err">${esc(e.message)}</td></tr>`;
  }
}

async function loadWorkers(){
  const t = tokenInput.value;
  try {
    const r = await fetch('/workers', {headers:{'X-Admin-Token': t}});
    if (r.status === 401) return;
    const d = await r.json();
    document.getElementById('workers').innerHTML = (d.workers || []).map(w => {
      const queues = (w.queues || []).map(q => `<span class="queue-tag">${esc(q)}</span>`).join('');
      const cats = (w.categories || []).join(', ');
      const active = w.active_tasks || 0;
      const activeList = (w.active_task_ids || []).length
        ? `<div class="wdetail">running: ${w.active_task_ids.map(esc).join(', ')}</div>` : '';
      return `<div class="worker-card">
        <div class="wname"><span class="dot ${w.status === 'online' ? 'online' : 'offline'}"></span>${esc(w.name)}</div>
        <div class="wdetail">${esc(w.type)} | categories: ${esc(cats)} | active tasks: ${active}${w.pool_size ? ' | concurrency: ' + w.pool_size : ''}</div>
        <div class="wdetail">${queues}</div>
        ${activeList}
      </div>`;
    }).join('') || '<div class="worker-card"><div class="wname"><span class="dot offline"></span>No workers</div></div>';
  } catch(e){ /* keep previous state */ }
}

async function loadClips(){
  const t = tokenInput.value;
  try {
    const r = await fetch('/clips', {headers:{'X-Admin-Token': t}});
    if (r.status === 401) return;
    const d = await r.json();
    const tree = d.tree || {};
    const cats = Object.keys(tree).sort();
    if (!cats.length){
      document.getElementById('clipTree').innerHTML = '<div class="muted" style="font-size:13px">No clips yet.</div>';
      return;
    }
    document.getElementById('clipTree').innerHTML = cats.map(cat => {
      const channels = tree[cat];
      const catCount = Object.values(channels).reduce((n, dates) =>
        n + Object.values(dates).reduce((m, clips) => m + clips.length, 0), 0);
      const channelHtml = Object.keys(channels).sort().map(channel => {
        const dates = channels[channel];
        const dateHtml = Object.keys(dates).sort().reverse().map(date => {
          const clips = dates[date];
          const clipHtml = clips.map(c =>
            `<div class="clip-item">&#9654; <a href="${esc(c.url)}" target="_blank">${esc(c.name)}</a><span class="size">${c.size_mb} MB &middot; ${esc(c.modified)}</span></div>`
          ).join('');
          return `<details><summary>&#128197; ${esc(date)} (${clips.length})</summary>${clipHtml}</details>`;
        }).join('');
        return `<details open><summary>&#128250; ${esc(channel)}</summary>${dateHtml}</details>`;
      }).join('');
      return `<details open><summary>&#128193; ${esc(cat)} (${catCount} clips)</summary>${channelHtml}</details>`;
    }).join('');
  } catch(e){ /* keep previous state */ }
}

function openNewEditModal(){
  document.getElementById('modalTitle').textContent = 'Create New Custom Edit';
  document.getElementById('modalTaskId').value = '';
  document.getElementById('modalClipStart').value = '0.0';
  document.getElementById('modalClipEnd').value = '30.0';
  document.getElementById('modalClipTitle').value = '';
  document.getElementById('modalToast').style.display = 'none';
  document.getElementById('editModal').style.display = 'flex';
}

function openEditModalForTask(taskId){
  document.getElementById('modalTitle').textContent = `Edit Clip: ${taskId}`;
  document.getElementById('modalTaskId').value = taskId;
  document.getElementById('modalClipStart').value = '0.0';
  document.getElementById('modalClipEnd').value = '30.0';
  document.getElementById('modalClipTitle').value = `Highlight from ${taskId}`;
  document.getElementById('modalToast').style.display = 'none';
  document.getElementById('editModal').style.display = 'flex';
}

function closeEditModal(){
  document.getElementById('editModal').style.display = 'none';
}

async function submitVideoEdit(){
  const t = tokenInput.value;
  const taskId = document.getElementById('modalTaskId').value.trim();
  const clipStart = parseFloat(document.getElementById('modalClipStart').value) || 0;
  const clipEnd = parseFloat(document.getElementById('modalClipEnd').value) || 30;
  const aspectRatio = document.getElementById('modalAspectRatio').value;
  const style = document.getElementById('modalStyle').value;
  const platform = document.getElementById('modalPlatform').value;
  const title = document.getElementById('modalClipTitle').value.trim();

  const toast = document.getElementById('modalToast');
  const renderBtn = document.getElementById('renderBtn');

  if (!taskId){
    toast.className = 'toast error';
    toast.textContent = 'Please enter a Task ID or video source.';
    toast.style.display = 'block';
    return;
  }

  renderBtn.disabled = true;
  renderBtn.textContent = 'Rendering with AMD AMF GPU...';
  toast.className = 'toast';
  toast.style.display = 'none';

  try {
    const res = await fetch(`/videos/${encodeURIComponent(taskId)}/edit`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Token': t,
      },
      body: JSON.stringify({
        clip_start: clipStart,
        clip_end: clipEnd,
        aspect_ratio: aspectRatio,
        style: style,
        platform: platform,
        title: title,
      }),
    });

    const data = await res.json();
    if (!res.ok){
      throw new Error(data.detail || 'Video editing failed.');
    }

    toast.className = 'toast success';
    toast.innerHTML = `&#10003; Clip created! <a href="${esc(data.url)}" target="_blank" style="color:var(--text);font-weight:bold;text-decoration:underline;">Click here to preview (${esc(data.aspect_ratio)})</a>`;
    toast.style.display = 'block';

    setTimeout(() => {
      loadVideos();
    }, 1000);

  } catch(err){
    toast.className = 'toast error';
    toast.textContent = 'Error: ' + err.message;
    toast.style.display = 'block';
  } finally {
    renderBtn.disabled = false;
    renderBtn.textContent = '⚙ Render Edited Clip';
  }
}

function refreshAll(){
  loadVideos();
  loadWorkers();
  loadClips();
}

if (tokenInput.value) refreshAll();
setInterval(() => { if (tokenInput.value) refreshAll(); }, 20000);
</script>
</body>
</html>
"""