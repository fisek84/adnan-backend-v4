from __future__ import annotations

from services.knowledge_snapshot_service import KnowledgeSnapshotService


def test_payload_databases_overrides_legacy_lists_to_prevent_stale_artifacts():
    # Simulate a bad/stale legacy payload list that contradicts databases SSOT.
    KnowledgeSnapshotService.update_snapshot(
        {
            "payload": {
                "goals": [{"id": "stale_goal"}],
                "tasks": [],
                "projects": [],
                "databases": {"goals": {"items": [], "row_count": 0}},
                "last_sync": "2026-01-01T00:00:00Z",
            },
            "meta": {"ok": True, "synced_at": "2026-01-01T00:00:00Z", "errors": []},
        }
    )

    snap = KnowledgeSnapshotService.get_snapshot()
    payload = snap.get("payload")
    assert isinstance(payload, dict)

    # Legacy list must mirror databases SSOT.
    assert payload.get("goals") == []
