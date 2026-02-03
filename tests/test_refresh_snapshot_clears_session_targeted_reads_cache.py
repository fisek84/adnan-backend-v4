from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient


class _Pol:
    def __init__(self, *, needs_notion: bool, notion_db_keys: List[str]):
        self.needs_notion = needs_notion
        self.notion_db_keys = notion_db_keys


class _StubNotionForChat:
    def __init__(self) -> None:
        self.calls: int = 0
        self._next_goals: List[Dict[str, Any]] = [{"id": "g1"}]

    def set_next_goals(self, goals: List[Dict[str, Any]]) -> None:
        self._next_goals = list(goals)

    async def build_knowledge_snapshot(
        self,
        *,
        db_keys: Optional[List[str]] = None,
        max_items_by_db: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        self.calls += 1
        synced_at = "2026-02-03T00:00:00Z"
        goals = list(self._next_goals)
        return {
            "payload": {
                "goals": goals,
                "tasks": [],
                "projects": [],
                "databases": {"goals": {"items": goals, "row_count": len(goals)}},
                "last_sync": synced_at,
            },
            "meta": {
                "ok": True,
                "synced_at": synced_at,
                "errors": [],
                "source": "stub_chat",
            },
        }


class _StubSyncService:
    def __init__(self) -> None:
        self.last_refresh_ok = True
        self.last_refresh_errors: List[Any] = []
        self.last_refresh_meta: Dict[str, Any] = {"ok": True, "errors": []}

    async def sync_knowledge_snapshot(self) -> bool:
        return True


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def test_refresh_snapshot_clears_session_targeted_reads_cache(monkeypatch: pytest.MonkeyPatch):
    # Make chat_router targeted reads eligible (it is normally disabled in tests).
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Ensure refresh endpoint does not do boot-time IO.
    monkeypatch.setenv("GATEWAY_SKIP_KNOWLEDGE_SYNC", "1")

    # Targeted reads on.
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "true")

    # Patch prompt classifier to always request Notion targeted reads.
    import services.grounding_policy as gp

    monkeypatch.setattr(gp, "classify_prompt", lambda prompt: _Pol(needs_notion=True, notion_db_keys=["goals"]))

    # Patch Notion service getter used by chat targeted reads.
    stub_notion = _StubNotionForChat()

    import services.notion_service as ns

    monkeypatch.setattr(ns, "get_or_init_notion_service", lambda: stub_notion)

    # Patch refresh snapshot sync service so refresh command succeeds.
    import dependencies as deps

    monkeypatch.setattr(deps, "get_sync_service", lambda: _StubSyncService())

    app = _get_app()
    client = TestClient(app)

    session_id = "sess_targeted_cache"

    # 1) First /api/chat call -> hits Notion and caches per-session.
    r1 = client.post(
        "/api/chat",
        json={
            "message": "show goals",
            "session_id": session_id,
            "metadata": {"include_debug": True},
        },
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    snap1 = b1.get("knowledge_snapshot")
    assert isinstance(snap1, dict)
    p1 = snap1.get("payload")
    assert isinstance(p1, dict)
    assert p1.get("goals") == [{"id": "g1"}]
    assert stub_notion.calls == 1

    # 2) Second /api/chat call same session -> uses session cache, no extra Notion call.
    stub_notion.set_next_goals([])  # would be returned if cache was NOT used
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    r2 = client.post(
        "/api/chat",
        json={
            "message": "show goals",
            "session_id": session_id,
            "metadata": {"include_debug": True},
        },
    )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    snap2 = b2.get("knowledge_snapshot")
    assert isinstance(snap2, dict)
    p2 = snap2.get("payload")
    assert isinstance(p2, dict)
    assert p2.get("goals") == [{"id": "g1"}]
    assert stub_notion.calls == 1

    # 3) refresh_snapshot -> clears session cache.
    rr = client.post(
        "/api/execute/raw",
        json={"intent": "refresh_snapshot", "command": "refresh_snapshot", "params": {}},
    )
    assert rr.status_code == 200, rr.text
    br = rr.json()
    assert br.get("execution_state") == "COMPLETED"

    # 4) /api/chat again same session -> must re-hit Notion and see empty goals.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    r3 = client.post(
        "/api/chat",
        json={
            "message": "show goals",
            "session_id": session_id,
            "metadata": {"include_debug": True},
        },
    )
    assert r3.status_code == 200, r3.text
    b3 = r3.json()
    snap3 = b3.get("knowledge_snapshot")
    assert isinstance(snap3, dict)
    p3 = snap3.get("payload")
    assert isinstance(p3, dict)
    assert p3.get("goals") == []
    assert stub_notion.calls == 2
