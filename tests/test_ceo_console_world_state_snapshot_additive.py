from __future__ import annotations

import os
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient


# Keep boot deterministic in unit tests.
os.environ.setdefault("GATEWAY_SKIP_KNOWLEDGE_SYNC", "1")
os.environ.setdefault("NOTION_PREFLIGHT_ON_BOOT", "false")


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_ceo_console_snapshot_adds_world_state_snapshot_without_notion_calls(
    monkeypatch: pytest.MonkeyPatch,
):
    # Arrange: deterministic cached knowledge snapshot
    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    KnowledgeSnapshotService.update_snapshot(
        {
            "payload": {
                "last_sync": "2026-03-09T00:00:00Z",
                "goals": [
                    {
                        "id": "g1",
                        "notion_id": "g1",
                        "title": "Increase Revenue",
                        "url": "",
                        "created_time": "2026-03-01T00:00:00Z",
                        "last_edited_time": "2026-03-08T00:00:00Z",
                        "fields": {
                            "status": "Active",
                            "progress": 50.0,
                            "due": {"start": "2026-03-30"},
                            "owner": ["ceo@example.com"],
                        },
                        "truncated": False,
                    }
                ],
                "projects": [
                    {
                        "id": "p1",
                        "notion_id": "p1",
                        "title": "Revamp Pricing",
                        "url": "",
                        "created_time": "2026-03-01T00:00:00Z",
                        "last_edited_time": "2026-03-08T00:00:00Z",
                        "fields": {
                            "status": "Active",
                            "priority": "High",
                            "target_deadline": {"start": "2026-03-20"},
                            "next_step": "Draft pricing tiers",
                            "primary_goal": ["g1"],
                        },
                        "truncated": False,
                    }
                ],
                "tasks": [
                    {
                        "id": "t1",
                        "notion_id": "t1",
                        "title": "Write pricing proposal",
                        "url": "",
                        "created_time": "2026-03-01T00:00:00Z",
                        "last_edited_time": "2026-03-08T00:00:00Z",
                        "fields": {
                            "status": "In Progress",
                            "priority": "High",
                            "due": {"start": "2026-03-10"},
                            "assigned_to": ["ceo@example.com"],
                            "goal": ["g1"],
                            "project": ["p1"],
                        },
                        "truncated": False,
                    }
                ],
            },
            "meta": {"ok": True, "synced_at": "2026-03-09T00:00:00Z"},
        }
    )

    # Arrange: stub legacy ceo_dashboard_snapshot builder to guarantee zero external IO.
    import gateway.gateway_server as gs

    monkeypatch.setattr(
        gs.CEOConsoleSnapshotService,
        "snapshot",
        lambda self: {"ok": True, "source": "test_stub"},
        raising=True,
    )

    # Arrange: hard-fail if any NotionService query path is hit during this request.
    # Do not require NotionService singleton init in this unit test.
    from services.notion_service import NotionService

    notion_calls: Dict[str, Any] = {"query_database": 0}

    async def _no_query_database(self: Any, *args: Any, **kwargs: Any):
        notion_calls["query_database"] += 1
        raise AssertionError("NotionService.query_database must not be called")

    monkeypatch.setattr(
        NotionService, "query_database", _no_query_database, raising=True
    )

    # Act
    app = _get_app()
    client = TestClient(app)
    r = client.get("/api/ceo/console/snapshot")

    # Assert
    assert r.status_code == 200
    body = r.json()

    assert "knowledge_snapshot" in body and isinstance(body["knowledge_snapshot"], dict)
    assert "world_state_snapshot" in body and isinstance(
        body["world_state_snapshot"], dict
    )

    ws = body["world_state_snapshot"]
    assert ws.get("trace", {}).get("snapshot_version") == "sotw.v1"

    # core business-state sections present
    assert isinstance(ws.get("goals"), dict)
    assert isinstance(ws.get("projects"), dict)
    assert isinstance(ws.get("tasks"), dict)

    # regression guard: our additive key must not introduce new Notion queries
    assert notion_calls["query_database"] == 0
