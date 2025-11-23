import sys, os
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

import unittest
from services.goals_service import GoalsService
from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate


class TestGoalsService(unittest.TestCase):

    def setUp(self):
        self.service = GoalsService()

    # ---------------------------------------------------------
    # CREATE GOAL
    # ---------------------------------------------------------
    def test_create_goal(self):
        data = GoalCreate(
            title="Test goal",
            description="Desc",
            deadline="2025-01-01",
            parent_id=None,
            priority="medium"
        )

        goal = self.service.create_goal(data)

        self.assertIsNotNone(goal.id)
        self.assertEqual(goal.title, "Test goal")
        self.assertEqual(goal.status, "pending")
        self.assertIn(goal.id, self.service.goals)
        self.assertEqual(goal.progress, 0)
        self.assertEqual(goal.children, [])

    # ---------------------------------------------------------
    # UPDATE GOAL
    # ---------------------------------------------------------
    def test_update_goal(self):
        created = self.service.create_goal(
            GoalCreate(
                title="Original",
                description="Desc",
                deadline="2025-01-01",
                parent_id=None,
                priority="low"
            )
        )

        goal_id = created.id

        updated = self.service.update_goal(
            goal_id,
            GoalUpdate(
                title="Updated Title",
                status="completed"
            )
        )

        self.assertEqual(updated.title, "Updated Title")
        self.assertEqual(updated.status, "completed")
        self.assertEqual(updated.description, "Desc")
        self.assertEqual(updated.id, goal_id)

    # ---------------------------------------------------------
    # DELETE GOAL
    # ---------------------------------------------------------
    def test_delete_goal(self):
        created = self.service.create_goal(
            GoalCreate(
                title="To delete",
                description="Delete me"
            )
        )

        goal_id = created.id
        deleted = self.service.delete_goal(goal_id)

        self.assertEqual(deleted.id, goal_id)
        self.assertNotIn(goal_id, self.service.goals)

    # ---------------------------------------------------------
    # MERGE GOALS
    # ---------------------------------------------------------
    def test_merge_goals(self):
        g1 = self.service.create_goal(
            GoalCreate(title="Goal A", description="Desc A")
        )

        g2 = self.service.create_goal(
            GoalCreate(title="Goal B", description="Desc B")
        )

        merged = self.service.merge_goals([g1.id, g2.id])

        self.assertIn("Goal A", merged.title)
        self.assertIn("Goal B", merged.title)
        self.assertIn("Desc A", merged.description)
        self.assertIn("Desc B", merged.description)

        self.assertNotIn(g1.id, self.service.goals)
        self.assertNotIn(g2.id, self.service.goals)

        self.assertIn(merged.id, self.service.goals)

    # ---------------------------------------------------------
    # AUTO PROGRESS
    # ---------------------------------------------------------
    def test_compute_auto_progress(self):
        g1 = self.service.create_goal(
            GoalCreate(title="Završeno: Izvještaj", description="Odradjeno sve")
        )
        g2 = self.service.create_goal(
            GoalCreate(title="Uradi plan", description="Treba završiti")
        )
        g3 = self.service.create_goal(
            GoalCreate(title="Nejasan cilj", description="Nedefinisano")
        )

        self.assertEqual(self.service.compute_auto_progress(g1.id), "completed")
        self.assertEqual(self.service.compute_auto_progress(g2.id), "in_progress")
        self.assertEqual(self.service.compute_auto_progress(g3.id), "unknown")


if __name__ == "__main__":
    unittest.main()