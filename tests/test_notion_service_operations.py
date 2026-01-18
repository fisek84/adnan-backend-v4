"""
Tests for NotionService operations (create_goal, create_task, create_project, update_page)
"""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from services.notion_service import NotionService
from models.ai_command import AICommand


class TestNotionServiceOperations(unittest.IsolatedAsyncioTestCase):
    """Test suite for NotionService extended operations."""

    def setUp(self):
        """Set up test NotionService instance with mocked dependencies."""
        self.service = NotionService(
            api_key="test_api_key",
            goals_db_id="test-goals-db-id",
            tasks_db_id="test-tasks-db-id",
            projects_db_id="test-projects-db-id",
        )
        # Mock the HTTP client
        self.service._client = AsyncMock()

    async def asyncTearDown(self):
        """Clean up resources."""
        await self.service.aclose()

    # ============================================================
    # CREATE GOAL TESTS
    # ============================================================

    async def test_create_goal_basic(self):
        """Test basic goal creation with required parameters only."""
        # Mock Notion API response
        mock_response = {
            "id": "goal-page-id-123",
            "url": "https://notion.so/goal-page-id-123",
            "properties": {},
        }

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            command = AICommand(
                command="notion_write",
                intent="create_goal",
                params={"title": "Test Goal"},
                approval_id="approval-123",
                execution_id="exec-123",
                read_only=False,
            )

            result = await self.service.execute(command)

            self.assertTrue(result["ok"])
            self.assertEqual(result["execution_state"], "COMPLETED")
            self.assertEqual(result["result"]["intent"], "create_goal")
            self.assertEqual(result["result"]["page_id"], "goal-page-id-123")
            self.assertEqual(result["approval_id"], "approval-123")

    async def test_create_goal_full_parameters(self):
        """Test goal creation with all optional parameters."""
        mock_response = {
            "id": "goal-page-id-456",
            "url": "https://notion.so/goal-page-id-456",
        }

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            command = AICommand(
                command="notion_write",
                intent="create_goal",
                params={
                    "title": "Complete Goal",
                    "description": "This is a detailed goal description",
                    "deadline": "2025-12-31",
                    "priority": "high",
                    "status": "in_progress",
                },
                approval_id="approval-456",
                execution_id="exec-456",
                read_only=False,
            )

            result = await self.service.execute(command)

            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["page_id"], "goal-page-id-456")

    async def test_create_goal_missing_title_fails(self):
        """Test that goal creation fails without title."""
        command = AICommand(
            command="notion_write",
            intent="create_goal",
            params={},
            approval_id="approval-789",
            execution_id="exec-789",
            read_only=False,
        )

        with self.assertRaises(RuntimeError) as context:
            await self.service.execute(command)

        self.assertIn("requires title", str(context.exception))

    # ============================================================
    # CREATE TASK TESTS
    # ============================================================

    async def test_create_task_basic(self):
        """Test basic task creation."""
        mock_response = {
            "id": "task-page-id-123",
            "url": "https://notion.so/task-page-id-123",
        }

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            command = AICommand(
                command="notion_write",
                intent="create_task",
                params={"title": "Test Task"},
                approval_id="approval-123",
                execution_id="exec-123",
                read_only=False,
            )

            result = await self.service.execute(command)

            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["intent"], "create_task")
            self.assertEqual(result["result"]["page_id"], "task-page-id-123")

    async def test_create_task_with_relations(self):
        """Test task creation with goal and project relations."""
        mock_create_response = {
            "id": "task-page-id-456",
            "url": "https://notion.so/task-page-id-456",
        }

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request, patch.object(
            self.service, "_update_page_relations", new_callable=AsyncMock
        ) as mock_update_relations:
            mock_request.return_value = mock_create_response

            command = AICommand(
                command="notion_write",
                intent="create_task",
                params={
                    "title": "Task with relations",
                    "goal_id": "goal-id-123",
                    "project_id": "project-id-456",
                },
                approval_id="approval-456",
                execution_id="exec-456",
                read_only=False,
            )

            result = await self.service.execute(command)

            self.assertTrue(result["ok"])
            # Verify that relations were updated
            mock_update_relations.assert_called_once_with(
                page_id="task-page-id-456",
                goal_id="goal-id-123",
                project_id="project-id-456",
            )

    # ============================================================
    # CREATE PROJECT TESTS
    # ============================================================

    async def test_create_project_basic(self):
        """Test basic project creation."""
        mock_response = {
            "id": "project-page-id-123",
            "url": "https://notion.so/project-page-id-123",
        }

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            command = AICommand(
                command="notion_write",
                intent="create_project",
                params={"title": "Test Project"},
                approval_id="approval-123",
                execution_id="exec-123",
                read_only=False,
            )

            result = await self.service.execute(command)

            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["intent"], "create_project")
            self.assertEqual(result["result"]["page_id"], "project-page-id-123")

    async def test_create_project_with_goal_relation(self):
        """Test project creation with primary goal relation."""
        mock_response = {
            "id": "project-page-id-456",
            "url": "https://notion.so/project-page-id-456",
        }

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request, patch.object(
            self.service, "_update_page_relations", new_callable=AsyncMock
        ) as mock_update_relations:
            mock_request.return_value = mock_response

            command = AICommand(
                command="notion_write",
                intent="create_project",
                params={
                    "title": "Project with goal",
                    "primary_goal_id": "goal-id-789",
                },
                approval_id="approval-789",
                execution_id="exec-789",
                read_only=False,
            )

            result = await self.service.execute(command)

            self.assertTrue(result["ok"])
            # Verify goal relation was updated
            mock_update_relations.assert_called_once_with(
                page_id="project-page-id-456",
                goal_id="goal-id-789",
            )

    # ============================================================
    # UPDATE PAGE TESTS
    # ============================================================

    async def test_update_page_basic(self):
        """Test basic page update."""
        mock_response = {
            "id": "page-id-123",
            "url": "https://notion.so/page-id-123",
        }

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            command = AICommand(
                command="notion_write",
                intent="update_page",
                params={
                    "page_id": "page-id-123",
                    "status": "completed",
                    "priority": "low",
                },
                approval_id="approval-123",
                execution_id="exec-123",
                read_only=False,
            )

            result = await self.service.execute(command)

            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["intent"], "update_page")
            self.assertEqual(result["result"]["page_id"], "page-id-123")

    async def test_update_page_with_relations(self):
        """Test page update with relation changes."""
        mock_response = {
            "id": "page-id-456",
            "url": "https://notion.so/page-id-456",
        }

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request, patch.object(
            self.service, "_update_page_relations", new_callable=AsyncMock
        ) as mock_update_relations:
            mock_request.return_value = mock_response

            command = AICommand(
                command="notion_write",
                intent="update_page",
                params={
                    "page_id": "page-id-456",
                    "goal_id": "new-goal-id",
                    "project_id": "new-project-id",
                },
                approval_id="approval-456",
                execution_id="exec-456",
                read_only=False,
            )

            result = await self.service.execute(command)

            self.assertTrue(result["ok"])
            # Verify relations were updated
            mock_update_relations.assert_called_once_with(
                page_id="page-id-456",
                goal_id="new-goal-id",
                project_id="new-project-id",
            )

    async def test_update_page_missing_page_id_fails(self):
        """Test that update fails without page_id."""
        command = AICommand(
            command="notion_write",
            intent="update_page",
            params={"status": "completed"},
            approval_id="approval-789",
            execution_id="exec-789",
            read_only=False,
        )

        with self.assertRaises(RuntimeError) as context:
            await self.service.execute(command)

        self.assertIn("requires page_id", str(context.exception))

    # ============================================================
    # PROPERTY HELPER TESTS
    # ============================================================

    def test_date_prop_helper(self):
        """Test _date_prop helper method."""
        result = self.service._date_prop("2025-12-31")
        self.assertEqual(result, {"date": {"start": "2025-12-31"}})

        # Empty date should return None
        result_empty = self.service._date_prop("")
        self.assertEqual(result_empty, {"date": None})

    def test_relation_prop_helper(self):
        """Test _relation_prop helper method."""
        result = self.service._relation_prop(["id-1", "id-2"])
        self.assertEqual(result, {"relation": [{"id": "id-1"}, {"id": "id-2"}]})

        # Empty list
        result_empty = self.service._relation_prop([])
        self.assertEqual(result_empty, {"relation": []})

    # ============================================================
    # READ-ONLY MODE TEST
    # ============================================================

    async def test_read_only_mode_noop(self):
        """Test that read_only=True returns noop without executing."""
        command = AICommand(
            command="notion_write",
            intent="create_goal",
            params={"title": "Test Goal"},
            approval_id="approval-123",
            execution_id="exec-123",
            read_only=True,  # READ-ONLY
        )

        result = await self.service.execute(command)

        self.assertTrue(result["ok"])
        self.assertTrue(result["read_only"])
        self.assertEqual(result["result"]["message"], "read_only_noop")

    # ============================================================
    # UNSUPPORTED INTENT TEST
    # ============================================================

    async def test_unsupported_intent_raises_error(self):
        """Test that unsupported intent raises RuntimeError."""
        command = AICommand(
            command="notion_write",
            intent="unsupported_operation",
            params={},
            approval_id="approval-999",
            execution_id="exec-999",
            read_only=False,
        )

        with self.assertRaises(RuntimeError) as context:
            await self.service.execute(command)

        self.assertIn("Unsupported intent", str(context.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
