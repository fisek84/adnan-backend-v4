from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient


def _ensure_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force gateway into test mode and skip boot-time network sync.
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("GATEWAY_SKIP_KNOWLEDGE_SYNC", "1")

    # Minimal required gateway env (no real secrets).
    monkeypatch.setenv("NOTION_API_KEY", "ntn_test")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "db_goals")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "db_tasks")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "db_projects")

    # Extra DBs: must be included in refresh snapshot automatically.
    monkeypatch.setenv("NOTION_KPI_DB_ID", "db_kpi")
    monkeypatch.setenv("NOTION_LEAD_DB_ID", "db_lead")


class _StubNotion:
    def __init__(self) -> None:
        self.calls: List[List[str]] = []
        self._next_payload_by_key: Dict[str, List[Dict[str, Any]]] = {}
        self._fail_keys: Dict[str, str] = {}

    def set_next_payload(self, *, by_key: Dict[str, List[Dict[str, Any]]]) -> None:
        self._next_payload_by_key = dict(by_key or {})
        self._fail_keys = {}

    def set_fail_keys(self, *, by_key: Dict[str, str]) -> None:
        self._fail_keys = dict(by_key or {})

    async def build_knowledge_snapshot(
        self,
        *,
        db_keys: Optional[List[str]] = None,
        max_items_by_db: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        keys = [str(k).strip().lower() for k in (db_keys or []) if str(k).strip()]
        self.calls.append(list(keys))

        synced_at = "2026-02-03T00:00:00Z"

        payload: Dict[str, Any] = {
            "goals": [],
            "tasks": [],
            "projects": [],
            "databases": {},
            "last_sync": synced_at,
        }
        meta: Dict[str, Any] = {
            "ok": True,
            "synced_at": synced_at,
            "source": "notion_stub",
            "errors": [],
            "db_stats": {},
        }

        for k in keys:
            if k in self._fail_keys:
                meta["ok"] = False
                meta["errors"].append(f"{k}:AuthError:{self._fail_keys[k]}")
                payload[k] = []
                payload["databases"][k] = {
                    "db_id": f"db_{k}",
                    "items": [],
                    "row_count": 0,
                    "last_refreshed_at": synced_at,
                    "last_error": {
                        "type": "AuthError",
                        "message": self._fail_keys[k],
                        "at": synced_at,
                    },
                }
                meta["db_stats"][k] = {
                    "ok": False,
                    "db_id": f"db_{k}",
                    "count": 0,
                    "error": f"AuthError:{self._fail_keys[k]}",
                    "duration_ms": 5,
                }
                continue

            items = list(self._next_payload_by_key.get(k, []))
            payload[k] = items
            payload["databases"][k] = {
                "db_id": f"db_{k}",
                "items": items,
                "row_count": int(len(items)),
                "last_refreshed_at": synced_at,
                "last_error": None,
            }
            meta["db_stats"][k] = {
                "ok": True,
                "db_id": f"db_{k}",
                "count": int(len(items)),
                "duration_ms": 5,
            }

        return {"payload": payload, "meta": meta}


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def test_refresh_snapshot_empty_dbs_multi_db(monkeypatch: pytest.MonkeyPatch):
    _ensure_test_env(monkeypatch)

    # Wire refresh_snapshot to our stubbed sync service.
    from services.notion_sync_service import NotionSyncService

    stub = _StubNotion()
    stub.set_next_payload(by_key={})

    sync = NotionSyncService(
        stub,
        goals_service=None,
        tasks_service=None,
        projects_service=None,
        goals_db_id="db_goals",
        tasks_db_id="db_tasks",
        projects_db_id="db_projects",
    )

    import dependencies as deps

    monkeypatch.setattr(deps, "get_sync_service", lambda: sync)

    # Seed session cache to prove invalidation.
    from services.session_snapshot_cache import SESSION_SNAPSHOT_CACHE

    SESSION_SNAPSHOT_CACHE.set(
        session_id="sess1",
        db_keys_csv="goals,tasks",
        value={"payload": {"goals": [{"id": "old"}]}},
        ttl_seconds=999,
    )

    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/execute/raw",
        json={
            "intent": "refresh_snapshot",
            "command": "refresh_snapshot",
            "params": {},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body.get("execution_state") == "COMPLETED"
    result = body.get("result")
    assert isinstance(result, dict)
    assert result.get("ok") is True

    ks = result.get("knowledge_snapshot")
    assert isinstance(ks, dict)
    payload = ks.get("payload")
    assert isinstance(payload, dict)

    dbs = payload.get("databases")
    assert isinstance(dbs, dict)

    # Must include ALL configured NOTION_*_DB_ID env vars (logical keys).
    for k in ("tasks", "projects", "goals", "kpi", "lead"):
        assert k in dbs
        assert dbs[k].get("row_count") == 0
        assert dbs[k].get("items") == []

    # Cache must be cleared on refresh.
    assert (
        SESSION_SNAPSHOT_CACHE.get(session_id="sess1", db_keys_csv="goals,tasks")
        is None
    )


def test_refresh_snapshot_partial_failure_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    _ensure_test_env(monkeypatch)

    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    # Seed old data; refresh must NOT overwrite it on failure.
    KnowledgeSnapshotService.update_snapshot(
        {
            "payload": {
                "goals": [{"id": "g_old"}],
                "tasks": [],
                "projects": [],
                "last_sync": "2026-01-01T00:00:00Z",
            },
            "meta": {"ok": True, "synced_at": "2026-01-01T00:00:00Z", "errors": []},
        }
    )

    from services.notion_sync_service import NotionSyncService

    stub = _StubNotion()
    stub.set_next_payload(by_key={"goals": [], "tasks": [], "projects": [], "lead": []})
    stub.set_fail_keys(by_key={"kpi": "invalid_token"})

    sync = NotionSyncService(
        stub,
        goals_service=None,
        tasks_service=None,
        projects_service=None,
        goals_db_id="db_goals",
        tasks_db_id="db_tasks",
        projects_db_id="db_projects",
    )

    import dependencies as deps

    monkeypatch.setattr(deps, "get_sync_service", lambda: sync)

    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/execute/raw",
        json={
            "intent": "refresh_snapshot",
            "command": "refresh_snapshot",
            "params": {},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body.get("execution_state") == "FAILED"
    result = body.get("result")
    assert isinstance(result, dict)
    assert result.get("ok") is False

    # Must report refresh errors without silently overwriting SSOT snapshot.
    refresh_errors = result.get("refresh_errors")
    assert isinstance(refresh_errors, list)
    assert any("kpi:AuthError" in str(e) for e in refresh_errors)

    refresh_meta = result.get("refresh_meta")
    assert isinstance(refresh_meta, dict)
    assert refresh_meta.get("ok") is False
    assert any("kpi:AuthError" in str(e) for e in (refresh_meta.get("errors") or []))

    ks = result.get("knowledge_snapshot")
    assert isinstance(ks, dict)
    # SSOT snapshot must remain the previous good snapshot.
    assert ks.get("status") in {"fresh", "stale", "missing_data"}

    meta = ks.get("meta")
    assert isinstance(meta, dict)
    assert meta.get("ok") is True

    payload = ks.get("payload")
    assert isinstance(payload, dict)

    assert payload.get("goals") == [{"id": "g_old"}]


def test_refresh_snapshot_overwrites_previous_snapshot(monkeypatch: pytest.MonkeyPatch):
    _ensure_test_env(monkeypatch)

    from services.notion_sync_service import NotionSyncService

    stub = _StubNotion()

    sync = NotionSyncService(
        stub,
        goals_service=None,
        tasks_service=None,
        projects_service=None,
        goals_db_id="db_goals",
        tasks_db_id="db_tasks",
        projects_db_id="db_projects",
    )

    import dependencies as deps

    monkeypatch.setattr(deps, "get_sync_service", lambda: sync)

    app = _get_app()
    client = TestClient(app)

    # First refresh: non-empty goals.
    stub.set_next_payload(by_key={"goals": [{"id": "g1"}]})
    r1 = client.post(
        "/api/execute/raw",
        json={
            "intent": "refresh_snapshot",
            "command": "refresh_snapshot",
            "params": {},
        },
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1.get("execution_state") == "COMPLETED"
    ks1 = b1.get("result", {}).get("knowledge_snapshot")
    assert isinstance(ks1, dict)
    assert isinstance(ks1.get("payload"), dict)
    assert len(ks1["payload"].get("goals") or []) == 1

    # Second refresh: goals become empty, must overwrite.
    stub.set_next_payload(by_key={"goals": []})
    r2 = client.post(
        "/api/execute/raw",
        json={
            "intent": "refresh_snapshot",
            "command": "refresh_snapshot",
            "params": {},
        },
    )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2.get("execution_state") == "COMPLETED"
    ks2 = b2.get("result", {}).get("knowledge_snapshot")
    assert isinstance(ks2, dict)
    payload2 = ks2.get("payload")
    assert isinstance(payload2, dict)
    assert payload2.get("goals") == []

    dbs2 = payload2.get("databases")
    assert isinstance(dbs2, dict)
    assert dbs2.get("goals", {}).get("row_count") == 0
