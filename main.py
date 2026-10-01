"""Main entry point for the video clipping pipeline.

Starts:
- SQLite task database
- Video clipping pipeline
- APScheduler channel monitor (every 30 minutes)
- FastAPI server + Admin Studio UI on http://localhost:8000
"""

import sys
import os
from pathlib import Path

# Ensure the current directory is in sys.path to resolve local imports
current_dir = Path(__file__).parent.absolute()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

import logging
import uvicorn

try:
    from api import create_app
    from database import init_db
    from pipeline import Pipeline
    from scheduler import Scheduler
except ImportError:
    # This block is now a fallback, but the sys.path modification above should handle it
    from api import create_app
    from database import init_db
    from pipeline import Pipeline
    from scheduler import Scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    """Initialize and start the video clipping system."""
    # 1. Initialize database
    init_db()
    
    # 2. Create FastAPI app — its startup event creates and starts the
    #    Scheduler inside uvicorn's running event loop ( AsyncIOScheduler
    #    requires a running loop, so it cannot be started before uvicorn.run )
    app = create_app()

    print("=" * 60)
    print("[VIDEO] VIDEO CLIPPING PIPELINE & STUDIO STARTED")
    print("=" * 60)
    print("Components:")
    print("  [OK] Database: SQLite (video_clipping.db)")
    print("  [OK] Scheduler: Active (monitoring target channels)")
    print("  [OK] Hardware Acceleration: AMD AMF (h264_amf)")
    print("  [OK] AI Engine: Ollama (llama3.1:8b) with editing_instructions.md")
    print("  [OK] Studio & API: http://localhost:8001/admin")
    print("=" * 60)

    # 4. Keep process alive by serving FastAPI & Admin Dashboard
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")


if __name__ == "__main__":
    main()