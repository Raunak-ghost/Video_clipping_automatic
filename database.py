"""Database module for storing task states, logs, and clip metadata.

Configures SQLite with WAL mode for concurrent-read safety and
provides a context‑manager interface for safe connection handling.
"""

import sqlite3
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Union, AsyncIterator
import logging

logger = logging.getLogger(__name__)


class Database:
    """Database handler supporting SQLite with WAL mode.

    Supports both synchronous and async usage. The connection is
    automatically configured with WAL journal mode and foreign keys.
    """

    def __init__(self, db_path: str = "video_clipping.db"):
        self.db_path = db_path
        self.conn: sqlite3.Connection = None  # type: ignore[assignment] - set by _init_db()
        self._init_db()

    def _init_db(self):
        """Initialize the database with required tables."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            # WAL mode allows concurrent readers while one writer is active
            self.conn.execute("PRAGMA journal_mode=WAL")
            # Foreign key enforcement
            self.conn.execute("PRAGMA foreign_keys=ON")
            self._create_tables()
            logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            raise

    def __enter__(self):
        """Support for 'with Database() as db:' syntax."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close the connection on exit."""
        self.close()
        return False

    async def __aenter__(self) -> "Database":
        """Support for async 'async with Database() as db:' syntax."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close the async connection on exit."""
        self.close()
        return False

    def close(self):
        """Close the database connection if open."""
        if self.conn:
            self.conn.close()
            self.conn = None  # type: ignore[assignment]
            logger.info("Database connection closed")

    def _create_tables(self):
        """Create all required tables."""
        cursor = self.conn.cursor()
        
        # Tasks table - stores task states
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                progress REAL DEFAULT 0.0,
                video_url TEXT,
                clip_path TEXT,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Logs table - stores processing logs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        """)
        
        # Clip metadata table - stores clip information
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clip_metadata (
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
            )
        """)
        
        # Migrate existing databases: CREATE TABLE IF NOT EXISTS won't add
        # columns to an already-created clip_metadata table.
        for column in ("title", "category", "channel"):
            try:
                cursor.execute(f"ALTER TABLE clip_metadata ADD COLUMN {column} TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists

        # Same for tasks.error (used when marking a task failed)
        try:
            cursor.execute("ALTER TABLE tasks ADD COLUMN error TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        
        # Webhooks table - stores webhook event history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                source TEXT,
                payload TEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed INTEGER DEFAULT 0
            )
        """)
        
        # Seen videos table - tracks processed video IDs to avoid re-processing
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seen_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT UNIQUE NOT NULL,
                category TEXT,
                channel_name TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.commit()

    def task_exists(self, task_id: str) -> bool:
        """Check if a task exists."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,))
        return cursor.fetchone() is not None

    def create_task(self, task_id: str, status: str = "pending") -> dict:
        """Create a new task record."""
        try:
            self.conn.execute(
                "INSERT INTO tasks (task_id, status) VALUES (?, ?)",
                (task_id, status),
            )
            self.conn.commit()
            return self.get_task(task_id)
        except sqlite3.IntegrityError:
            logger.warning(f"Task {task_id} already exists")
            return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict:
        """Get task details."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        )
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return {}

    def list_tasks(self, status: Optional[str] = None, limit: int = 100) -> list:
        """List tasks, newest first, optionally filtered by status."""
        cursor = self.conn.cursor()
        if status:
            cursor.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def count_by_status(self) -> dict:
        """Return task counts grouped by status."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status")
        return {row[0]: row[1] for row in cursor.fetchall()}

    def get_task_logs(self, task_db_id: int) -> list:
        """Get log entries for a task (by primary key)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM logs WHERE task_id = ? ORDER BY created_at DESC",
            (task_db_id,),
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_clips(self, task_db_id: int) -> list:
        """Get clip metadata for a task (by primary key)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM clip_metadata WHERE task_id = ?", (task_db_id,)
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def update_task_status(self, task_id: str, status: str, **kwargs) -> bool:
        """Update task status and optional fields."""
        try:
            update_fields = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
            params = [status]
            
            for key, value in kwargs.items():
                update_fields.append(f"{key} = ?")
                params.append(value)
            
            params.append(task_id)
            query = f"UPDATE tasks SET {', '.join(update_fields)} WHERE task_id = ?"
            
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to update task {task_id}: {e}")
            return False

    def log_message(self, task_id: int, level: str, message: str) -> int:
        """Add a log entry for a task."""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO logs (task_id, level, message) VALUES (?, ?, ?)",
            (task_id, level, message),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def create_clip_metadata(
        self,
        task_id: Any,
        clip_start: float,
        clip_end: float,
        duration: float,
        output_path: str,
        social_platform: Optional[str] = None,
        title: Optional[str] = None,
        category: Optional[str] = None,
        channel: Optional[str] = None,
        posted_at: Optional[Union[str, datetime]] = None,
    ) -> int:
        """Create clip metadata record. Accepts integer task PK or string task_id.

        If ``posted_at`` is not provided, it defaults to the current UTC timestamp.
        """
        db_task_id = task_id
        if isinstance(task_id, str):
            task_row = self.get_task(task_id)
            if task_row and "id" in task_row:
                db_task_id = task_row["id"]
            else:
                db_task_id = None
        
        if posted_at is None:
            posted_at = datetime.now(timezone.utc)
        elif isinstance(posted_at, datetime):
            posted_at = posted_at.isoformat()
        
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO clip_metadata "
            "(task_id, clip_start, clip_end, duration, output_path, social_platform, title, category, channel, posted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (db_task_id, clip_start, clip_end, duration, output_path, social_platform, title, category, channel, posted_at),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    # Seen videos methods
    def video_seen(self, video_id: str) -> bool:
        """Check if a video has been processed."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM seen_videos WHERE video_id = ?", (video_id,))
        return cursor.fetchone() is not None

    def mark_video_seen(self, video_id: str, category: Optional[str] = None, channel_name: Optional[str] = None) -> bool:
        """Mark a video as processed."""
        try:
            self.conn.execute(
                "INSERT OR IGNORE INTO seen_videos (video_id, category, channel_name) VALUES (?, ?, ?)",
                (video_id, category, channel_name),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to mark video {video_id} as seen: {e}")
            return False

    def get_seen_videos(self) -> set:
        """Get all seen video IDs."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT video_id FROM seen_videos")
        return {row[0] for row in cursor.fetchall()}


def init_db(db_path: str = "video_clipping.db") -> Database:
    """Initialize the database and return a Database instance.

    Creates the database file and tables if they don't exist,
    and returns a Database instance with an active connection.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        A Database instance with connection initialized and tables created.
    """
    db = Database(db_path)
    return db


def close(db: Database) -> None:
    """Close the database connection.
    
    Args:
        db: Database instance to close.
    """
    if db.conn:
        db.conn.close()
        logger.info("Database connection closed")