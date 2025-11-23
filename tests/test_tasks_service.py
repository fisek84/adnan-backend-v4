import os
import sys
import unittest

# Ensure project root is importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.tasks_service import TasksService
from models.task_create import TaskCreate
from models.task_update import TaskUpdate


class TestTasksService(unittest.TestCase):

    def setUp(self):
        """
        Reset service for every test.
        Guarantees full isolation and avoids cross-test contamination.
        """
        self.service = TasksService()

    # ---------------------------------------------------------
    # CREATE TASK
    # ---------------------------------------------------------
    def test_create_task(self):
        payload = TaskCreate(
            title="Test task",
            description="Test description",
            goal_id=None,
            deadline="2025-01-01",
            priority="high"
        )

        task = self.service.create_task(payload)

        self.assertIsNotNone(task.id, "Task ID should be generated")
        self.assertEqual(task.title, "Test task")
        self.assertEqual(task.description, "Test description")
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.priority, "high")
        self.assertIsNotNone(task.created_at)
        self.assertIsNotNone(task.updated_at)
        self.assertIn(task.id, self.service.tasks)

    # ---------------------------------------------------------
    # UPDATE TASK
    # ---------------------------------------------------------
    def test_update_task(self):
        task = self.service.create_task(
            TaskCreate(
                title="Original task",
                description="Old description",
                priority="low"
            )
        )

        updated = self.service.update_task(
            task.id,
            TaskUpdate(
                title="Updated title",
                status="completed",
            )
        )

        self.assertEqual(updated.id, task.id)
        self.assertEqual(updated.title, "Updated title")
        self.assertEqual(updated.status, "completed")
        self.assertEqual(updated.description, "Old description")

    # ---------------------------------------------------------
    # DELETE TASK
    # ---------------------------------------------------------
    def test_delete_task(self):
        task = self.service.create_task(TaskCreate(title="To delete"))

        deleted = self.service.delete_task(task.id)

        self.assertEqual(deleted.id, task.id)
        self.assertNotIn(task.id, self.service.tasks)

    # ---------------------------------------------------------
    # ASSIGN TASK TO GOAL
    # ---------------------------------------------------------
    def test_assign_task(self):
        task = self.service.create_task(TaskCreate(title="Unassigned"))

        updated = self.service.assign_task(task.id, "goal123")

        self.assertEqual(updated.goal_id, "goal123")
        self.assertIn(task.id, self.service.tasks)

    # ---------------------------------------------------------
    # REORDER TASKS
    # ---------------------------------------------------------
    def test_reorder_tasks(self):
        t1 = self.service.create_task(TaskCreate(title="T1"))
        t2 = self.service.create_task(TaskCreate(title="T2"))
        t3 = self.service.create_task(TaskCreate(title="T3"))

        new_order = [t3.id, t1.id, t2.id]

        result = self.service.reorder_tasks(new_order)

        self.assertEqual([t.id for t in result], new_order)
        self.assertEqual(list(self.service.tasks.keys()), new_order)

    # ---------------------------------------------------------
    # GENERATE TASK FROM GOAL
    # ---------------------------------------------------------
    def test_generate_task_from_goal(self):
        class FakeGoal:
            id = "g123"
            title = "Napravi sistem"
            description = "Detaljno definirati module"
            deadline = "2025-01-01"
            priority = "high"

        task = self.service.generate_task_from_goal(FakeGoal)

        self.assertIn(task.id, self.service.tasks)
        self.assertEqual(task.goal_id, FakeGoal.id)
        self.assertEqual(task.title, f"Task: {FakeGoal.title}")
        self.assertEqual(task.priority, FakeGoal.priority)
        self.assertEqual(task.description, FakeGoal.description)

    # ---------------------------------------------------------
    # MISSING TASK HANDLING
    # ---------------------------------------------------------
    def test_update_missing_task(self):
        with self.assertRaises(KeyError):
            self.service.update_task("does-not-exist", TaskUpdate(title="X"))

    def test_delete_missing_task(self):
        with self.assertRaises(KeyError):
            self.service.delete_task("missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)