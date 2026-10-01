"""Consolidated Database Verification & Integration Tests."""

import os
from database import init_db, close, Database

TEST_DB_PATH = "test_video_clipping.db"


def run_tests():
    # Clean up leftover test DB if any
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    print("--- 1. Testing init_db() ---")
    db = init_db(TEST_DB_PATH)
    print("init_db() returned:", type(db))
    print("Connection:", db.conn)

    print("\n--- 2. Verifying Tables Created ---")
    cursor = db.conn.cursor()
    cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
    tables = [row[0] for row in cursor.fetchall()]
    print("Tables created:", tables)

    print("\n--- 3. Testing Task CRUD Operations ---")
    db.create_task("test_task_1")
    task = db.get_task("test_task_1")
    print("Created task:", task)
    assert task is not None, "Task creation failed!"
    assert task["task_id"] == "test_task_1"

    db.update_task_status("test_task_1", status="completed", progress=100.0)
    updated_task = db.get_task("test_task_1")
    print("Updated task:", updated_task)
    assert updated_task["status"] == "completed"

    print("\n--- 4. Testing Logging & Clip Metadata ---")
    log_id = db.log_message(1, "INFO", "Processing started successfully.")
    print("Log recorded with ID:", log_id)
    assert log_id is not None

    clip_id = db.create_clip_metadata(1, 0.0, 30.0, 30.0, "clips/clip1.mp4", "twitter")
    print("Clip metadata recorded with ID:", clip_id)
    assert clip_id is not None

    print("\n--- 5. Testing close() function ---")
    close(db)
    print("close() executed successfully")

    print("\n--- 6. Testing direct Database class instantiation ---")
    db2 = Database(TEST_DB_PATH)
    print("Database() returned:", type(db2))
    close(db2)

    # Clean up test database file
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    print("\nTest database cleaned up successfully!")


if __name__ == "__main__":
    run_tests()