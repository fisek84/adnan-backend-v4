from __future__ import annotations

import unittest

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
    def __init__(self, *, data=None):
        self.data = data or {}

    async def request(self, method, url, params=None, json=None):
        return _DummyResp(self.data)


class TestSnapshotAssignedToPeopleMapping(unittest.IsolatedAsyncioTestCase):
    async def test_assigned_to_people_mapped_to_normalized_assigned_to(self):
        svc = NotionService(
            api_key="test_api_key",
            goals_db_id="test-goals-db-id",
            tasks_db_id="test-tasks-db-id",
            projects_db_id="test-projects-db-id",
        )

        page1 = {
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "url": "https://notion.so/x",
            "created_time": "2026-03-01T00:00:00Z",
            "last_edited_time": "2026-03-02T00:00:00Z",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Goal A"}]},
                "Assigned To": {
                    "type": "people",
                    "people": [
                        {
                            "name": "Alice",
                            "person": {"email": "alice@example.com"},
                        }
                    ],
                },
            },
        }

        page2 = {
            "id": "ffffffff-1111-2222-3333-444444444444",
            "url": "https://notion.so/y",
            "created_time": "2026-03-03T00:00:00Z",
            "last_edited_time": "2026-03-04T00:00:00Z",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Goal B"}]},
                "assigned_to": {
                    "type": "people",
                    "people": [{"name": "Bob"}],
                },
            },
        }

        dummy = _DummyClient(data={"results": [page1, page2], "has_more": False})

        async def _get_client():
            return dummy

        svc._get_client = _get_client  # type: ignore[method-assign]

        wrapper = await svc.build_knowledge_snapshot(db_keys=["goals"])
        await svc.aclose()

        payload = wrapper.get("payload") if isinstance(wrapper, dict) else None
        self.assertIsInstance(payload, dict)
        goals = payload.get("goals")
        self.assertIsInstance(goals, list)
        self.assertEqual(len(goals), 2)

        # Find items by title (more stable than id normalization differences).
        by_title = {it.get("title"): it for it in goals if isinstance(it, dict)}
        a_fields = (by_title.get("Goal A") or {}).get("fields")
        b_fields = (by_title.get("Goal B") or {}).get("fields")

        self.assertIsInstance(a_fields, dict)
        self.assertIsInstance(b_fields, dict)

        self.assertEqual(a_fields.get("assigned_to"), ["alice@example.com"])
        self.assertEqual(b_fields.get("assigned_to"), ["Bob"])
