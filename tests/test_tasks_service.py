import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from services.tasks_service import TasksService
from models.task_create import TaskCreate
from models.task_update import TaskUpdate


class TestTasksService(unittest.TestCase):

    def setUp(self):
        self.service = TasksService()

    # ---------------------------------------------------------
    # CREATE TASK
    # ---------------------------------------------------------
    def test_create_task(self):
        data = TaskCreate(
            title="Test task",
            description="Desc",
            goal_id=None,
            deadline="2025-01-01",
            priority="high"
        )

        task = self.service.create_task(data)

        self.assertIsNotNone(task.id)
        self.assertEqual(task.title, "Test task")
        self.assertEqual(task.status, "pending")
        self.assertIn(task.id, self.service.tasks)
        self.assertEqual(task.priority, "high")
        self.assertIsNotNone(task.created_at)
        self.assertIsNotNone(task.updated_at)

    # ---------------------------------------------------------
    # UPDATE TASK
    # ---------------------------------------------------------
    def test_update_task(self):
        task = self.service.create_task(
            TaskCreate(
                title="Original task",
                description="Old desc",
                priority="low"
            )
        )

        updated = self.service.update_task(
            task.id,
            TaskUpdate(
                title="Updated task",
                status="completed"
            )
        )

        self.assertEqual(updated.title, "Updated task")
        self.assertEqual(updated.status, "completed")
        self.assertEqual(updated.description, "Old desc")
        self.assertEqual(updated.id, task.id)

    # ---------------------------------------------------------
    # DELETE TASK
    # ---------------------------------------------------------
    def test_delete_task(self):
        task = self.service.create_task(
            TaskCreate(title="To delete", description="Remove me")
        )

        deleted = self.service.delete_task(task.id)

        self.assertEqual(deleted.id, task.id)
        self.assertNotIn(task.id, self.service.tasks)

    # ---------------------------------------------------------
    # ASSIGN TASK
    # ---------------------------------------------------------
    def test_assign_task(self):
        task = self.service.create_task(TaskCreate(title="Unassigned task"))

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

        ordered = [t3.id, t1.id, t2.id]

        result = self.service.reorder_tasks(ordered)

        self.assertEqual([t.id for t in result], ordered)
        self.assertEqual(list(self.service.tasks.keys()), ordered)

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
        self.assertEqual(task.title, "Task: Napravi sistem")
        self.assertEqual(task.priority, "high")


if __name__ == "__main__":
    unittest.main()
