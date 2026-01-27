from __future__ import annotations

import os
import random
import unittest
from typing import Any, Dict
from unittest.mock import patch

from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.notion_service import NotionService


class _DummyResp:
    def __init__(self, data: Dict[str, Any]):
        self.status_code = 200
        self._data = data

    @property
    def text(self) -> str:
        return "{}"

    def json(self) -> Dict[str, Any]:
        return self._data


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return float(self.t)

    def advance_ms(self, ms: int) -> None:
        self.t += float(ms) / 1000.0


def _notion_query_payload(title: str) -> Dict[str, Any]:
    return {
        "results": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "url": "https://notion.so/x",
                "created_time": "2026-01-01T00:00:00Z",
                "last_edited_time": "2026-01-01T00:00:00Z",
                "properties": {
                    "Name": {"type": "title", "title": [{"plain_text": title}]}
                },
            }
        ],
        "has_more": False,
        "next_cursor": None,
    }


def _mk_service() -> NotionService:
    return NotionService(
        api_key="test_api_key",
        goals_db_id="db-goals",
        tasks_db_id="db-tasks",
        projects_db_id="db-projects",
    )


class TestNotionSnapshotLatencyBudgetOverrides(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_default_4000ms_all_dbs_ready(self):
        clock = _FakeClock()
        service = _mk_service()

        class _Client:
            async def request(self, method, url, params=None, json=None):
                # Order is tasks -> projects -> goals (enforced by service).
                if "/databases/db-tasks/query" in url:
                    clock.advance_ms(1200)
                    return _DummyResp(_notion_query_payload("Task 1"))
                if "/databases/db-projects/query" in url:
                    clock.advance_ms(1800)
                    return _DummyResp(_notion_query_payload("Project 1"))
                if "/databases/db-goals/query" in url:
                    clock.advance_ms(1640)
                    return _DummyResp(_notion_query_payload("Goal 1"))
                return _DummyResp({"results": [], "has_more": False})

        async def _get_client():
            return _Client()

        service._get_client = _get_client  # type: ignore[method-assign]

        with patch("services.notion_service.time.monotonic", clock.monotonic):
            with patch.dict(
                os.environ,
                {
                    "CEO_NOTION_MAX_CALLS": "50",
                },
                clear=False,
            ):
                # Ensure CEO snapshot defaults apply (no explicit env set).
                for k in (
                    "CEO_NOTION_MAX_LATENCY_MS",
                    "CEO_NOTION_MAX_LATENCY_MS_GOALS",
                    "CEO_NOTION_MAX_LATENCY_MS_PROJECTS",
                    "CEO_NOTION_MAX_LATENCY_MS_TASKS",
                ):
                    os.environ.pop(k, None)

                wrapper = await service.build_knowledge_snapshot()

        self.assertIsInstance(wrapper, dict)
        meta = wrapper.get("meta")
        self.assertIsInstance(meta, dict)
        self.assertTrue(bool(meta.get("ok")))
        self.assertEqual(meta.get("errors"), [])

        KnowledgeSnapshotService.update_snapshot(wrapper)
        snap = KnowledgeSnapshotService.get_snapshot()
        self.assertTrue(bool(snap.get("ready")))
        self.assertEqual(snap.get("status"), "fresh")

        payload = snap.get("payload")
        self.assertIsInstance(payload, dict)
        self.assertIsInstance(payload.get("tasks"), list)
        self.assertIsInstance(payload.get("projects"), list)
        self.assertIsInstance(payload.get("goals"), list)
        self.assertEqual(len(payload.get("tasks") or []), 1)
        self.assertEqual(len(payload.get("projects") or []), 1)
        self.assertEqual(len(payload.get("goals") or []), 1)

        await service.aclose()

    async def test_snapshot_projects_latency_override_triggers_budget_exceeded(self):
        clock = _FakeClock()
        service = _mk_service()

        class _Client:
            async def request(self, method, url, params=None, json=None):
                if "/databases/db-tasks/query" in url:
                    clock.advance_ms(1200)
                    return _DummyResp(_notion_query_payload("Task 1"))
                if "/databases/db-projects/query" in url:
                    clock.advance_ms(1800)
                    return _DummyResp(_notion_query_payload("Project 1"))
                if "/databases/db-goals/query" in url:
                    clock.advance_ms(1640)
                    return _DummyResp(_notion_query_payload("Goal 1"))
                return _DummyResp({"results": [], "has_more": False})

        async def _get_client():
            return _Client()

        service._get_client = _get_client  # type: ignore[method-assign]

        with patch("services.notion_service.time.monotonic", clock.monotonic):
            with patch.dict(
                os.environ,
                {
                    "CEO_NOTION_MAX_CALLS": "50",
                    "CEO_NOTION_MAX_LATENCY_MS_PROJECTS": "1000",
                },
                clear=False,
            ):
                # Ensure globals are unset so per-DB override is decisive.
                for k in (
                    "CEO_NOTION_MAX_LATENCY_MS",
                    "CEO_NOTION_MAX_LATENCY_MS_GOALS",
                    "CEO_NOTION_MAX_LATENCY_MS_TASKS",
                ):
                    os.environ.pop(k, None)

                wrapper = await service.build_knowledge_snapshot()

        meta = wrapper.get("meta") if isinstance(wrapper, dict) else {}
        self.assertIsInstance(meta, dict)
        self.assertFalse(bool(meta.get("ok")))
        errs = meta.get("errors")
        self.assertIsInstance(errs, list)
        self.assertIn("projects:budget_exceeded:max_latency_ms", errs)

        KnowledgeSnapshotService.update_snapshot(wrapper)
        snap = KnowledgeSnapshotService.get_snapshot()
        self.assertFalse(bool(snap.get("ready")))
        self.assertEqual(snap.get("status"), "missing_data")

        await service.aclose()

    async def test_snapshot_latency_smoke_no_budget_exceeded(self):
        rng = random.Random(1337)

        for _ in range(20):
            clock = _FakeClock()
            service = _mk_service()

            t_tasks = rng.randint(800, 2400)
            t_projects = rng.randint(800, 2400)
            t_goals = rng.randint(800, 2400)

            class _Client:
                async def request(self, method, url, params=None, json=None):
                    if "/databases/db-tasks/query" in url:
                        clock.advance_ms(t_tasks)
                        return _DummyResp(_notion_query_payload("Task 1"))
                    if "/databases/db-projects/query" in url:
                        clock.advance_ms(t_projects)
                        return _DummyResp(_notion_query_payload("Project 1"))
                    if "/databases/db-goals/query" in url:
                        clock.advance_ms(t_goals)
                        return _DummyResp(_notion_query_payload("Goal 1"))
                    return _DummyResp({"results": [], "has_more": False})

            async def _get_client():
                return _Client()

            service._get_client = _get_client  # type: ignore[method-assign]

            with patch("services.notion_service.time.monotonic", clock.monotonic):
                with patch.dict(
                    os.environ,
                    {
                        "CEO_NOTION_MAX_CALLS": "50",
                    },
                    clear=False,
                ):
                    for k in (
                        "CEO_NOTION_MAX_LATENCY_MS",
                        "CEO_NOTION_MAX_LATENCY_MS_GOALS",
                        "CEO_NOTION_MAX_LATENCY_MS_PROJECTS",
                        "CEO_NOTION_MAX_LATENCY_MS_TASKS",
                    ):
                        os.environ.pop(k, None)

                    wrapper = await service.build_knowledge_snapshot()

            meta = wrapper.get("meta") if isinstance(wrapper, dict) else {}
            self.assertIsInstance(meta, dict)
            self.assertTrue(bool(meta.get("ok")))
            self.assertEqual(meta.get("errors"), [])

            await service.aclose()
