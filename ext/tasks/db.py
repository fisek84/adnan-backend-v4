import sqlite3
import os
import json
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
            error TEXT,
            metadata TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_task(task_id, payload, metadata=None):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO tasks (
            id,
            status,
            payload,
            metadata,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        task_id,
        "queued",
        payload,
        json.dumps(metadata or {}),
        datetime.utcnow().isoformat(),
        datetime.utcnow().isoformat(),
    ))

    conn.commit()
    conn.close()


def update_task(task_id, status, result=None, error=None):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tasks
        SET
            status = ?,
            result = ?,
            error = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        status,
        result,
        error,
        datetime.utcnow().isoformat(),
        task_id,
    ))

    conn.commit()
    conn.close()


def get_task(task_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()

    conn.close()

    if not row:
        return None

    data = dict(row)

    # normalize metadata
    try:
        data["metadata"] = json.loads(data.get("metadata") or "{}")
    except Exception:
        data["metadata"] = {}

    return data
