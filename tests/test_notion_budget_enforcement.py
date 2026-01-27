import os
import unittest
from unittest.mock import patch

from services.notion_service import NotionService


class _DummyResp:
    def __init__(self, data=None):
        self.status_code = 200
        self._data = data or {}

    @property
    def text(self):
        return "{}"

    def json(self):
        return self._data


class _DummyClient:
    def __init__(self, *, advance_s=None, data=None):
        # advance_s: optional callable invoked on each request to advance fake time.
        self.advance_s = advance_s
        self.data = data or {}
        self.calls = 0

    async def request(self, method, url, params=None, json=None):
        self.calls += 1
        if callable(self.advance_s):
            self.advance_s()
        return _DummyResp(self.data)


class TestNotionBudgets(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = NotionService(
            api_key="test_api_key",
            goals_db_id="test-goals-db-id",
            tasks_db_id="test-tasks-db-id",
            projects_db_id="test-projects-db-id",
        )

    async def asyncTearDown(self):
        await self.service.aclose()

    async def test_budget_max_calls_enforced(self):
        # Fake monotonic clock (no sleeps).
        now = {"t": 0.0}

        def _mono():
            return float(now["t"])

        def _advance():
            # Keep under any reasonable latency budget.
            now["t"] += 0.0001

        dummy = _DummyClient(
            advance_s=_advance, data={"results": [], "has_more": False}
        )

        async def _get_client():
            return dummy

        self.service._get_client = _get_client  # type: ignore[method-assign]

        with patch("services.notion_service.time.monotonic", _mono):
            with patch.dict(
                os.environ,
                {
                    "CEO_NOTION_MAX_CALLS": "1",
                    "CEO_NOTION_MAX_LATENCY_MS": "999999",
                },
                clear=False,
            ):
                snap = await self.service.build_knowledge_snapshot()

        meta = snap.get("meta") if isinstance(snap, dict) else {}
        self.assertIsInstance(meta, dict)
        self.assertFalse(bool(meta.get("ok")))

        budget = meta.get("budget")
        self.assertIsInstance(budget, dict)
        self.assertTrue(bool(budget.get("exceeded")))
        self.assertEqual(budget.get("exceeded_kind"), "max_calls")

        self.assertEqual(int(meta.get("notion_calls") or 0), 1)

    async def test_budget_max_latency_enforced(self):
        # Fake monotonic clock advanced by the dummy client (no sleeps).
        now = {"t": 0.0}

        def _mono():
            return float(now["t"])

        def _advance():
            # 2ms virtual request latency.
            now["t"] += 0.002

        dummy = _DummyClient(
            advance_s=_advance, data={"results": [], "has_more": False}
        )

        async def _get_client():
            return dummy

        self.service._get_client = _get_client  # type: ignore[method-assign]

        with patch("services.notion_service.time.monotonic", _mono):
            with patch.dict(
                os.environ,
                {
                    "CEO_NOTION_MAX_CALLS": "50",
                    "CEO_NOTION_MAX_LATENCY_MS": "1",
                },
                clear=False,
            ):
                snap = await self.service.build_knowledge_snapshot()

        meta = snap.get("meta") if isinstance(snap, dict) else {}
        self.assertIsInstance(meta, dict)
        self.assertFalse(bool(meta.get("ok")))

        budget = meta.get("budget")
        self.assertIsInstance(budget, dict)
        self.assertTrue(bool(budget.get("exceeded")))
        self.assertEqual(budget.get("exceeded_kind"), "max_latency_ms")

        self.assertEqual(int(meta.get("notion_calls") or 0), 1)
