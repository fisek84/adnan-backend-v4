import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.getcwd(), "tasks.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            status TEXT,
            payload TEXT,
            result TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    conn.commit()
    conn.close()

def save_task(task_id, payload):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO tasks (id, status, payload, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
    """, (task_id, "queued", payload, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))

    conn.commit()
    conn.close()

def update_task(task_id, status, result=None):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tasks
        SET status = ?, result = ?, updated_at = ?
        WHERE id = ?
    """, (status, result, datetime.utcnow().isoformat(), task_id))

    conn.commit()
    conn.close()

def get_task(task_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()

    conn.close()
    return dict(row) if row else None
