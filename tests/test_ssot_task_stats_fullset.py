from __future__ import annotations


from services.ssot_task_query_engine import compute_task_stats


def test_compute_task_stats_prefers_payload_tasks_over_dashboard_subset() -> None:
    # dashboard.tasks is often top-N; stats must use the full payload.tasks set.
    snapshot = {
        "ready": True,
        "status": "fresh",
        "schema_version": "v1",
        "payload": {
            "tasks": [
                {"id": "t1", "title": "A", "status": "Not Started"},
                {"id": "t2", "title": "B", "status": "In Progress"},
                {"id": "t3", "title": "C", "status": "Done"},
                {"id": "t4", "title": "D", "status": "Not Started"},
            ],
            "dashboard": {
                "tasks": [
                    {"id": "t1", "title": "A", "status": "Not Started"},
                ]
            },
        },
    }

    stats = compute_task_stats(snapshot)
    assert stats["total_count"] == 4
    # Active = total - completed/done
    assert stats["active_count"] == 3
