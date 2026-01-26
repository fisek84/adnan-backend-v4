from __future__ import annotations


def test_snapshot_not_ready_when_meta_ok_false_budget_exceeded_and_payload_empty():
    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    KnowledgeSnapshotService.update_snapshot(
        {
            "payload": {},
            "meta": {
                "ok": False,
                "errors": ["budget_exceeded"],
                "budget": {"exceeded": True, "exceeded_kind": "max_latency_ms"},
                "source": "test",
                "synced_at": "2026-01-26T00:00:00Z",
            },
        }
    )

    snap = KnowledgeSnapshotService.get_snapshot()
    assert isinstance(snap, dict)

    assert snap.get("ready") is False
    assert snap.get("status") == "missing_data"
    assert snap.get("status_detail") == "error"
