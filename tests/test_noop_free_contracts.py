from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_informational_no_proposals(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Objasni kako radi approval flow u ovom sistemu.",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    pcs = body.get("proposed_commands") or []
    assert isinstance(pcs, list)
    assert pcs == []


def test_notion_reads_when_needed_via_snapshot(monkeypatch):
    """In tests we stay offline: we simulate Notion read by injecting a snapshot.

    The acceptance condition here is: operational task question -> notion_snapshot should be marked used.
    """

    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")

    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    # Inject a minimal viable snapshot with tasks.
    KnowledgeSnapshotService.update_snapshot(
        {
            "payload": {
                "goals": [],
                "projects": [],
                "tasks": [{"id": "t1", "title": "Active task (test)"}],
                "last_sync": "2026-01-22T00:00:00Z",
            },
            "meta": {"ok": True, "source": "test"},
        }
    )

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Koji su mi aktivni taskovi?",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    pcs = body.get("proposed_commands") or []
    assert isinstance(pcs, list)
    assert pcs == []

    tr2 = body.get("trace_v2")
    assert isinstance(tr2, dict)
    used = tr2.get("used_sources")
    assert isinstance(used, list)
    assert "notion_snapshot" in used
