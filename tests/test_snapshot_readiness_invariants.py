from __future__ import annotations


def test_snapshot_not_ready_when_meta_ok_false_budget_exceeded_and_payload_empty():
    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    # Use a current timestamp to avoid flakiness due to TTL-based expiration.
    from datetime import datetime, timezone

    now_iso = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    KnowledgeSnapshotService.update_snapshot(
        {
            "payload": {},
            "meta": {
                "ok": False,
                "errors": ["budget_exceeded"],
                "budget": {"exceeded": True, "exceeded_kind": "max_latency_ms"},
                "source": "test",
                "synced_at": now_iso,
            },
        }
    )

    snap = KnowledgeSnapshotService.get_snapshot()
    assert isinstance(snap, dict)

    assert snap.get("ready") is False
    assert snap.get("status") == "missing_data"
    assert snap.get("status_detail") == "error"
