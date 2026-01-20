"""
Tests for NotionService operations (create_goal, create_task, create_project, update_page)
"""

import unittest
from unittest.mock import AsyncMock, patch

import os

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
        if hasattr(self, "service") and self.service:
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

    async def test_create_task_resolves_goal_by_title(self):
        """If goal_id is missing but goal_title is provided, service should link by best-effort lookup."""
        mock_create_response = {
            "id": "task-page-id-999",
            "url": "https://notion.so/task-page-id-999",
        }

        # Notion database query response for goals
        mock_query_response = {
            "results": [
                {
                    "id": "goal-page-id-xyz",
                    "properties": {"Name": {"title": [{"plain_text": "ADNAN RAMBO"}]}},
                }
            ]
        }

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request, patch.object(
            self.service, "_update_page_relations", new_callable=AsyncMock
        ) as mock_update_relations:

            async def fake_safe_request(method, url, payload=None, params=None):
                # Schema reads
                if method == "GET" and "/databases/" in url:
                    return {"properties": {}}

                # Create task page
                if method == "POST" and url.endswith("/pages"):
                    return mock_create_response

                # Query goals DB
                if method == "POST" and "/databases/" in url and url.endswith("/query"):
                    if "test-goals-db-id" in url:
                        return mock_query_response
                    return {"results": []}

                return {}

            mock_request.side_effect = fake_safe_request

            command = AICommand(
                command="notion_write",
                intent="create_task",
                params={
                    "title": "Task with goal title",
                    "goal_title": "ADNAN RAMBO",
                },
                approval_id="approval-999",
                execution_id="exec-999",
                read_only=False,
            )

            result = await self.service.execute(command)
            self.assertTrue(result["ok"], msg=str(result))

            mock_update_relations.assert_called_once_with(
                page_id="task-page-id-999",
                goal_id="goal-page-id-xyz",
                project_id="",
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
    # PEOPLE / ASSIGNEE TESTS
    # ============================================================

    async def test_create_page_people_property_specs_resolve_users(self):
        """People specs should resolve to Notion user IDs and be sent as people[]."""

        captured_payloads = []

        async def fake_safe_request(method, url, payload=None, params=None):
            # Users listing for people resolution
            if method == "GET" and url.endswith("/users"):
                return {
                    "results": [
                        {
                            "id": "user-123",
                            "name": "Adnan X",
                            "person": {"email": "adnan@example.com"},
                        }
                    ]
                }

            # Schema reads (ignored/minimal)
            if method == "GET" and "/databases/" in url:
                return {"properties": {}}

            # Page create: capture payload
            if method == "POST" and url.endswith("/pages"):
                captured_payloads.append(payload or {})
                return {
                    "id": "page-id-with-people",
                    "url": "https://notion.so/page-id-with-people",
                }

            return {}

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = fake_safe_request

            command = AICommand(
                command="notion_write",
                intent="create_page",
                params={
                    "db_key": "tasks",
                    "property_specs": {
                        "Name": {"type": "title", "text": "Task with assignee"},
                        "AI Agent": {
                            "type": "people",
                            "names": ["Adnan X", "adnan@example.com"],
                        },
                    },
                },
                approval_id="approval-people-1",
                execution_id="exec-people-1",
                read_only=False,
            )

            result = await self.service.execute(command)
            self.assertTrue(result["ok"], msg=str(result))
            self.assertTrue(captured_payloads, "No payload captured for POST /pages")

            properties = captured_payloads[0].get("properties") or {}
            self.assertIn("AI Agent", properties)
            people_prop = properties["AI Agent"]
            self.assertIsInstance(people_prop, dict)
            people_list = people_prop.get("people")
            self.assertIsInstance(people_list, list)
            self.assertIn({"id": "user-123"}, people_list)

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

    async def test_update_page_stable_id_targeting_tasks(self):
        """Update should resolve page_id via stable id when not provided."""

        captured = {"queried": False, "patched_urls": []}

        async def fake_safe_request(method, url, payload=None, params=None):
            # Schema for db_id
            if method == "GET" and "/databases/" in url:
                return {
                    "properties": {
                        "Task ID": {"type": "rich_text"},
                        "Status": {"type": "select", "select": {"options": []}},
                    }
                }

            if method == "POST" and url.endswith("/query"):
                captured["queried"] = True
                return {"results": [{"id": "page-from-stable-id"}]}

            if method == "PATCH" and "/pages/" in url:
                captured["patched_urls"].append(url)
                return {"id": "page-from-stable-id", "url": "https://notion.so/page"}

            return {}

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = fake_safe_request

            cmd = AICommand(
                command="notion_write",
                intent="update_page",
                params={
                    "db_key": "tasks",
                    "task_id": "T-001",
                    "status": "Completed",
                },
                approval_id="approval-stable-1",
                execution_id="exec-stable-1",
                read_only=False,
            )

            res = await self.service.execute(cmd)

            self.assertTrue(res["ok"], msg=str(res))
            self.assertTrue(captured["queried"], "Expected DB query for stable id")
            self.assertIn("page-from-stable-id", res["result"]["page_id"])

    async def test_delete_page_stable_id_targeting_tasks(self):
        """Delete should resolve page_id via stable id when not provided."""

        async def fake_safe_request(method, url, payload=None, params=None):
            if method == "GET" and "/databases/" in url:
                return {"properties": {"Task ID": {"type": "rich_text"}}}

            if method == "POST" and url.endswith("/query"):
                return {"results": [{"id": "page-del-from-stable-id"}]}

            if method == "PATCH" and "/pages/" in url:
                return {
                    "id": "page-del-from-stable-id",
                    "url": "https://notion.so/page",
                }

            return {}

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = fake_safe_request

            cmd = AICommand(
                command="notion_write",
                intent="delete_page",
                params={
                    "db_key": "tasks",
                    "task_id": "T-DELETE-1",
                },
                approval_id="approval-del-stable-1",
                execution_id="exec-del-stable-1",
                read_only=False,
            )

            res = await self.service.execute(cmd)
            self.assertTrue(res["ok"], msg=str(res))
            self.assertEqual(res["result"]["page_id"], "page-del-from-stable-id")

    def test_resolve_db_id_from_env_discovery(self):
        """NotionService should resolve arbitrary db_key from NOTION_*_DB_ID env."""
        old = dict(os.environ)
        try:
            os.environ["NOTION_CUSTOMERS_DB_ID"] = "db-customers-123"
            svc = NotionService(
                api_key="k",
                goals_db_id="g",
                tasks_db_id="t",
                projects_db_id="p",
            )
            self.assertEqual(svc._resolve_db_id("customers"), "db-customers-123")
        finally:
            os.environ.clear()
            os.environ.update(old)

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

    # ============================================================
    # BATCH / DELETE (ENTERPRISE)
    # ============================================================

    async def test_delete_page_archives(self):
        """Test that delete_page archives a page via PATCH."""
        mock_response = {
            "id": "page-id-123",
            "url": "https://notion.so/page-id-123",
            "archived": True,
        }

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            command = AICommand(
                command="notion_write",
                intent="delete_page",
                params={"page_id": "page-id-123"},
                approval_id="approval-123",
                execution_id="exec-123",
                read_only=False,
            )

            result = await self.service.execute(command)
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["intent"], "delete_page")
            mock_request.assert_called_once()

    async def test_batch_request_runs_operations_and_resolves_refs(self):
        """Test batch_request executes multiple ops and resolves $op_id references."""
        # Simulate create_goal then create_task that references the created goal
        create_goal_res = {
            "id": "goal-page-id-1",
            "url": "https://notion.so/goal-page-id-1",
        }
        create_task_res = {
            "id": "task-page-id-1",
            "url": "https://notion.so/task-page-id-1",
        }

        captured_payloads = []

        with patch.object(
            self.service, "_safe_request", new_callable=AsyncMock
        ) as mock_request, patch.object(
            self.service, "_update_page_relations", new_callable=AsyncMock
        ) as mock_update_relations:
            created = {"count": 0}

            async def fake_safe_request(method, url, payload=None, params=None):
                # DB schema reads
                if method == "GET" and "/databases/" in url:
                    return {"properties": {}}

                # Page creates
                if method == "POST" and url.endswith("/pages"):
                    created["count"] += 1
                    captured_payloads.append(payload or {})
                    return create_goal_res if created["count"] == 1 else create_task_res

                return {}

            mock_request.side_effect = fake_safe_request

            command = AICommand(
                command="notion_write",
                intent="batch_request",
                params={
                    "operations": [
                        {
                            "op_id": "goal_1",
                            "intent": "create_goal",
                            "payload": {"title": "Goal A"},
                        },
                        {
                            "op_id": "task_1",
                            "intent": "create_task",
                            "payload": {
                                "title": "Task A",
                                "goal_id": "$goal_1",
                                "description": "$goal_1 :: linked",
                            },
                        },
                    ]
                },
                approval_id="approval-batch",
                execution_id="exec-batch",
                read_only=False,
            )

            result = await self.service.execute(command)
            self.assertTrue(result["ok"], msg=str(result))

            # Expect both ops ok
            ops = result.get("result", {}).get("operations", [])
            self.assertEqual(len(ops), 2)
            self.assertTrue(ops[0]["ok"])
            self.assertTrue(ops[1]["ok"])

            # Task relations should be updated with resolved goal page id
            mock_update_relations.assert_called_once_with(
                page_id="task-page-id-1",
                goal_id="goal-page-id-1",
                project_id="",
            )

            # '$op_id' prefix replacement should also apply inside strings.
            # Second payload corresponds to task creation.
            self.assertGreaterEqual(len(captured_payloads), 2)
            task_payload = captured_payloads[1]
            props = task_payload.get("properties") or {}
            desc = props.get("Description") or {}
            rt = desc.get("rich_text") if isinstance(desc, dict) else None
            self.assertIsInstance(rt, list)
            content = rt[0].get("text", {}).get("content") if rt else ""
            self.assertIn("goal-page-id-1", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
