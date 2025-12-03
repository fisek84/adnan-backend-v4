import os
import sys
import unittest

# Ensure project root is importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.goals_service import GoalsService
from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate


class TestGoalsService(unittest.TestCase):

    def setUp(self):
        """Reset service before every test for full isolation."""
        self.service = GoalsService()

    # ---------------------------------------------------------
    # CREATE GOAL
    # ---------------------------------------------------------
    def test_create_goal(self):
        payload = GoalCreate(
            title="Test goal",
            description="Desc",
            deadline="2025-01-01",
            parent_id=None,
            priority="medium"
        )

        goal = self.service.create_goal(payload)

        self.assertIsNotNone(goal.id, "Goal must have an ID")
        self.assertEqual(goal.title, "Test goal")
        self.assertEqual(goal.priority, "medium")
        self.assertEqual(goal.status, "pending")
        self.assertEqual(goal.progress, 0)
        self.assertEqual(goal.children, [])
        self.assertIn(goal.id, self.service.goals)

    # ---------------------------------------------------------
    # UPDATE GOAL
    # ---------------------------------------------------------
    def test_update_goal(self):
        original = self.service.create_goal(
            GoalCreate(title="Original", description="Desc")
        )

        updated = self.service.update_goal(
            original.id,
            GoalUpdate(
                title="Updated Title",
                status="completed"
            )
        )

        self.assertEqual(updated.id, original.id)
        self.assertEqual(updated.title, "Updated Title")
        self.assertEqual(updated.status, "completed")
        self.assertEqual(updated.description, "Desc")

    # ---------------------------------------------------------
    # UPDATE NON-EXISTENT GOAL
    # ---------------------------------------------------------
    def test_update_goal_missing(self):
        with self.assertRaises(KeyError):
            self.service.update_goal("does-not-exist", GoalUpdate(title="X"))

    # ---------------------------------------------------------
    # DELETE GOAL
    # ---------------------------------------------------------
    def test_delete_goal(self):
        created = self.service.create_goal(
            GoalCreate(title="To delete", description="Delete me")
        )

        deleted = self.service.delete_goal(created.id)

        self.assertEqual(deleted.id, created.id)
        self.assertNotIn(created.id, self.service.goals)

    # ---------------------------------------------------------
    # DELETE NON-EXISTENT GOAL
    # ---------------------------------------------------------
    def test_delete_missing_goal(self):
        with self.assertRaises(KeyError):
            self.service.delete_goal("missing-id")

    # ---------------------------------------------------------
    # MERGE GOALS
    # ---------------------------------------------------------
    def test_merge_goals(self):
        g1 = self.service.create_goal(GoalCreate(title="Goal A", description="Desc A"))
        g2 = self.service.create_goal(GoalCreate(title="Goal B", description="Desc B"))

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
        # Completed goal
        g1 = self.service.create_goal(
            GoalCreate(title="Završeno: Izvještaj", description="Gotovo sve")
        )
        # Active goal
        g2 = self.service.create_goal(
            GoalCreate(title="Uradi plan", description="Skoro sve")
        )
        # Unknown status
        g3 = self.service.create_goal(
            GoalCreate(title="Nejasan cilj", description="Nedefinisano")
        )

        self.assertEqual(self.service.compute_auto_progress(g1.id), "completed")
        self.assertEqual(self.service.compute_auto_progress(g2.id), "in_progress")
        self.assertEqual(self.service.compute_auto_progress(g3.id), "unknown")

    # ---------------------------------------------------------
    # PARENT - CHILD RELATION
    # ---------------------------------------------------------
    def test_parent_child_assignment(self):
        parent = self.service.create_goal(
            GoalCreate(title="Parent goal", description="Main")
        )
        child = self.service.create_goal(
            GoalCreate(title="Child goal", description="Sub", parent_id=parent.id)
        )

        self.assertIn(child.id, self.service.goals)
        self.assertEqual(child.parent_id, parent.id)
        self.assertIn(child.id, parent.children)

    # ---------------------------------------------------------
    # MERGING SINGLE GOAL SHOULD RETURN SAME GOAL
    # ---------------------------------------------------------
    def test_merge_single_goal(self):
        g = self.service.create_goal(
            GoalCreate(title="Solo", description="Only one")
        )

        merged = self.service.merge_goals([g.id])

        self.assertEqual(merged.id, g.id)
        self.assertEqual(merged.title, g.title)
        self.assertEqual(merged.description, g.description)

    # ---------------------------------------------------------
    # INVALID MERGE (NON-EXISTENT ID)
    # ---------------------------------------------------------
    def test_merge_with_missing_goal(self):
        g = self.service.create_goal(GoalCreate(title="Valid", description="OK"))

        with self.assertRaises(KeyError):
            self.service.merge_goals([g.id, "does-not-exist"])


if __name__ == "__main__":
    unittest.main(verbosity=2)