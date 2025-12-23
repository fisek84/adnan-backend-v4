import sqlite3
import unittest

from services.goals_service import GoalsService
from models.goal_create import GoalCreate


class TestGoalsService(unittest.TestCase):
    def setUp(self) -> None:
        """In-memory SQLite + GoalsService za svaki test (full isolation)."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.service = GoalsService(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------
    # CREATE GOAL
    # ---------------------------------------------------------
    def test_create_goal_basic(self) -> None:
        payload = GoalCreate(
            title="Test goal",
            description="Desc",
            deadline="2025-01-01",
            parent_id=None,
            priority="medium",
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
    # GET ALL
    # ---------------------------------------------------------
    def test_get_all_returns_created_goal(self) -> None:
        g1 = self.service.create_goal(GoalCreate(title="Goal 1", description="Desc 1"))
        g2 = self.service.create_goal(GoalCreate(title="Goal 2", description="Desc 2"))

        all_goals = self.service.get_all()
        ids = {g.id for g in all_goals}

        self.assertIn(g1.id, ids)
        self.assertIn(g2.id, ids)
        self.assertEqual(len(all_goals), 2)

    # ---------------------------------------------------------
    # PERSISTENCE ROUNDTRIP (SQLite)
    # ---------------------------------------------------------
    def test_load_from_db_roundtrip(self) -> None:
        created = self.service.create_goal(
            GoalCreate(
                title="Persisted goal",
                description="Should survive reload",
                deadline="2025-12-31",
                parent_id=None,
                priority="high",
            )
        )
        goal_id = created.id

        # Poništi in-memory cache
        self.service.goals.clear()
        self.assertEqual(len(self.service.goals), 0)

        # Re-load iz SQLite
        self.service.load_from_db()

        self.assertIn(goal_id, self.service.goals)
        loaded = self.service.goals[goal_id]
        self.assertEqual(loaded.title, "Persisted goal")
        self.assertEqual(loaded.priority, "high")
        self.assertEqual(loaded.status, "pending")


if __name__ == "__main__":
    unittest.main(verbosity=2)
