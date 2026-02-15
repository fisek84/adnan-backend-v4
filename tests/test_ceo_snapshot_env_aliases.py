import datetime as dt

import pytest


class _DummyResponse:
    def __init__(self, *, status_code: int, payload: dict):
        self.status_code = int(status_code)
        self._payload = payload
        self.text = "OK"

    def json(self):
        return self._payload


def test_ceo_snapshot_env_db_id_only_not_unconfigured(monkeypatch: pytest.MonkeyPatch):
    """Regression: CEO snapshot must work with canonical *_DB_ID only.

    Scenario:
      - NOTION_API_KEY + NOTION_GOALS_DB_ID + NOTION_TASKS_DB_ID set
      - legacy *_DATABASE_ID NOT set
      - network stubbed

    Expect:
      - snapshot.available is True (not 'snapshot service not configured')
      - metadata has per-db configured/unconfigured flags
    """

    # --- Minimal canonical env ---
    monkeypatch.setenv("NOTION_API_KEY", "test_notion_api_key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "goals_db_123")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "tasks_db_456")

    monkeypatch.delenv("NOTION_GOALS_DATABASE_ID", raising=False)
    monkeypatch.delenv("NOTION_TASKS_DATABASE_ID", raising=False)

    # --- Stub KnowledgeSnapshotService (avoid depending on snapshot refresh state) ---
    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    monkeypatch.setattr(
        KnowledgeSnapshotService,
        "get_snapshot",
        classmethod(
            lambda cls: {
                "schema_version": "v1",
                "status": "fresh",
                "generated_at": dt.datetime.utcnow().isoformat(),
                "last_sync": dt.datetime.utcnow().isoformat(),
                "payload": {"goals": [], "tasks": [], "projects": []},
                "ready": True,
                "expired": False,
                "trace": {"ttl_seconds": None, "age_seconds": None, "is_expired": False},
            }
        ),
        raising=True,
    )

    # --- Stub requests network used by CEO snapshot service (_NotionClient) ---
    import requests

    def _stub_request(self, method: str, url: str, *args, **kwargs):
        method_u = (method or "").upper()

        # Database query endpoint (goals/tasks)
        if method_u == "POST" and "/databases/" in url and url.endswith("/query"):
            return _DummyResponse(
                status_code=200,
                payload={"results": [], "next_cursor": None},
            )

        # Any GETs are not expected in this test, but keep fail-soft.
        if method_u == "GET":
            return _DummyResponse(status_code=200, payload={})

        return _DummyResponse(status_code=200, payload={})

    monkeypatch.setattr(requests.sessions.Session, "request", _stub_request, raising=True)

    # --- Execute ---
    from services.ceo_console_snapshot_service import CeoConsoleSnapshotService

    snap = CeoConsoleSnapshotService().snapshot()

    assert isinstance(snap, dict)
    assert snap.get("available") is True
    assert snap.get("error") not in ("snapshot service not configured", "Snapshot service not ready")

    dash = snap.get("dashboard")
    assert isinstance(dash, dict)
    meta = dash.get("metadata")
    assert isinstance(meta, dict)

    dbs = meta.get("databases")
    assert isinstance(dbs, dict)

    assert dbs.get("goals", {}).get("configured") is True
    assert dbs.get("tasks", {}).get("configured") is True

    # Optional sections must not force the entire snapshot missing.
    assert dbs.get("approvals", {}).get("configured") is False
    assert dbs.get("sop", {}).get("configured") is False
    assert dbs.get("plans", {}).get("configured") is False
