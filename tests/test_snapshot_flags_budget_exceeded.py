from __future__ import annotations

from fastapi.testclient import TestClient


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def test_api_chat_snapshot_flags_not_fresh_when_budget_exceeded(monkeypatch):
    """Regression: if snapshot meta shows budget exceeded/errors, trace.snapshot
    must not claim fresh/ready/ok.
    """

    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    bad_snapshot = {
        "schema_version": "v1",
        "status": "fresh",
        "ready": True,
        "expired": False,
        "generated_at": "2026-01-26T00:00:00Z",
        "last_sync": "2026-01-26T00:00:00Z",
        "ttl_seconds": 3600,
        "age_seconds": 0,
        "meta": {
            "ok": True,
            "errors": ["goals:budget_exceeded:max_latency_ms"],
            "budget": {"exceeded": True, "exceeded_kind": "max_latency_ms"},
        },
        "payload": {"goals": [], "tasks": [], "projects": []},
    }

    monkeypatch.setattr(
        KnowledgeSnapshotService,
        "get_snapshot",
        classmethod(lambda cls: dict(bad_snapshot)),
    )

    app = _get_app()
    client = TestClient(app)

    r = client.post("/api/chat", json={"message": "debug used_sources"})
    assert r.status_code == 200, r.text

    body = r.json()
    tr = body.get("trace")
    assert isinstance(tr, dict)

    snap = tr.get("snapshot")
    assert isinstance(snap, dict)

    # Required invariants
    assert snap.get("ready") is False
    assert snap.get("status") in ("partial", "error")

    meta = snap.get("meta")
    assert isinstance(meta, dict)
    assert meta.get("ok") is False
    assert meta.get("reason") == "budget_exceeded"

    errs = meta.get("errors")
    assert isinstance(errs, list)
    assert "goals:budget_exceeded:max_latency_ms" in errs

    budget = meta.get("budget")
    assert isinstance(budget, dict)
    assert budget.get("exceeded") is True
