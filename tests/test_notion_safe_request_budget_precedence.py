import unittest
from unittest.mock import AsyncMock, patch

from services.notion_service import (
    NotionBudgetExceeded,
    NotionService,
    notion_budget_context,
)


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = int(status_code)
        self.text = text

    def json(self):  # noqa: ANN201
        return {}


class TestNotionSafeRequestBudgetPrecedence(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        if hasattr(self, "service") and self.service:
            await self.service.aclose()

    async def test_http_401_not_masked_by_budget_exceeded(self) -> None:
        self.service = NotionService(
            api_key="test",
            goals_db_id="g",
            tasks_db_id="t",
            projects_db_id="p",
        )

        fake_client = AsyncMock()
        fake_client.request = AsyncMock(
            return_value=_FakeResponse(401, '{"message":"unauthorized"}')
        )

        # Control time so:
        # - budget context starts at t=100.0
        # - pre-request budget check sees elapsed=0ms (passes)
        # - post-request budget check would see elapsed>0ms (would exceed)
        with (
            patch(
                "services.notion_service.time.monotonic",
                side_effect=[100.0, 100.0, 100.003],
            ),
            patch.object(
                self.service, "_get_client", new=AsyncMock(return_value=fake_client)
            ),
        ):
            async with notion_budget_context(max_calls=10, max_latency_ms=0):
                with self.assertRaises(RuntimeError) as ctx:
                    await self.service._safe_request(
                        "POST",
                        "https://api.notion.com/v1/databases/x/query",
                        payload={"page_size": 1},
                    )

        self.assertIn("Notion HTTP 401", str(ctx.exception))

    async def test_budget_exceeded_still_raises_on_success(self) -> None:
        self.service = NotionService(
            api_key="test",
            goals_db_id="g",
            tasks_db_id="t",
            projects_db_id="p",
        )

        fake_client = AsyncMock()
        fake_client.request = AsyncMock(return_value=_FakeResponse(200, "{}"))

        with (
            patch(
                "services.notion_service.time.monotonic",
                side_effect=[200.0, 200.0, 200.003],
            ),
            patch.object(
                self.service, "_get_client", new=AsyncMock(return_value=fake_client)
            ),
        ):
            async with notion_budget_context(max_calls=10, max_latency_ms=0):
                with self.assertRaises(NotionBudgetExceeded) as ctx:
                    await self.service._safe_request(
                        "GET",
                        "https://api.notion.com/v1/users/me",
                        payload=None,
                    )

        self.assertEqual("max_latency_ms", str(ctx.exception))
