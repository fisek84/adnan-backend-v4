import sqlite3
import unittest

from services.tasks_service import TasksService
from models.task_create import TaskCreate


class TestTasksService(unittest.TestCase):
    def setUp(self) -> None:
        """In-memory SQLite + TasksService za svaki test (full isolation)."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.service = TasksService(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------
    # CREATE TASK
    # ---------------------------------------------------------
    def test_create_task_basic(self) -> None:
        payload = TaskCreate(
            title="Test task",
            description="Test description",
            goal_id=None,
            deadline="2025-01-01",
            priority="high",
        )

        task = self.service.create_task(payload)

        self.assertIsNotNone(task.id, "Task ID should be generated")
        self.assertEqual(task.title, "Test task")
        self.assertEqual(task.description, "Test description")
        self.assertEqual(task.priority, "high")
        # Pretpostavka kao u domenu: novi task je pending
        self.assertEqual(task.status, "pending")
        self.assertIsNotNone(task.created_at)
        self.assertIsNotNone(task.updated_at)
        self.assertIn(task.id, self.service.tasks)

    # ---------------------------------------------------------
    # GET ALL
    # ---------------------------------------------------------
    def test_get_all_returns_created_tasks(self) -> None:
        t1 = self.service.create_task(TaskCreate(title="Task 1", description="Desc 1"))
        t2 = self.service.create_task(TaskCreate(title="Task 2", description="Desc 2"))

        all_tasks = self.service.get_all()
        ids = {t.id for t in all_tasks}

        self.assertIn(t1.id, ids)
        self.assertIn(t2.id, ids)
        self.assertEqual(len(all_tasks), 2)

    # ---------------------------------------------------------
    # PERSISTENCE ROUNDTRIP (SQLite)
    # ---------------------------------------------------------
    def test_load_from_db_roundtrip(self) -> None:
        created = self.service.create_task(
            TaskCreate(
                title="Persisted task",
                description="Should survive reload",
                goal_id=None,
                deadline="2025-12-31",
                priority="medium",
            )
        )
        task_id = created.id

        # Poništi in-memory cache
        self.service.tasks.clear()
        self.assertEqual(len(self.service.tasks), 0)

        # Re-load iz SQLite
        self.service.load_from_db()

        self.assertIn(task_id, self.service.tasks)
        loaded = self.service.tasks[task_id]
        self.assertEqual(loaded.title, "Persisted task")
        self.assertEqual(loaded.priority, "medium")
        self.assertEqual(loaded.status, "pending")


if __name__ == "__main__":
    unittest.main(verbosity=2)
