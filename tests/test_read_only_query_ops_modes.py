from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_read_only_query_ops_snapshot_health_is_deterministic() -> None:
    from services.tool_runtime_executor import execute

    out = await execute(
        "read_only.query",
        {"action": "read_only.query", "query": "ops.snapshot_health"},
        agent_id="dept_ops",
        execution_id="exec_test_1",
    )

    assert isinstance(out, dict)
    assert out.get("ok") is True
    assert out.get("execution_state") == "COMPLETED"
    assert isinstance(out.get("data"), dict)
    assert out["data"].get("kind") == "ops.snapshot_health"
    assert isinstance(out.get("meta"), dict)
    assert out["meta"].get("query") == "ops.snapshot_health"


@pytest.mark.anyio
async def test_read_only_query_ops_daily_brief_is_deterministic() -> None:
    from services.tool_runtime_executor import execute

    # Seed snapshot with fields so the brief is non-empty.
    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    KnowledgeSnapshotService.update_snapshot(
        {
            "payload": {
                "last_sync": "2026-02-10T00:00:00Z",
                "databases": {
                    "tasks": {
                        "db_id": "db_tasks",
                        "items": [
                            {
                                "id": "t1",
                                "notion_id": "t1",
                                "title": "Call 5 leads",
                                "url": "",
                                "created_time": "2026-02-01T00:00:00Z",
                                "last_edited_time": "2026-02-09T00:00:00Z",
                                "fields": {
                                    "status": "In Progress",
                                    "priority": "Urgent",
                                    "due": "2026-02-05",
                                },
                            },
                            {
                                "id": "t2",
                                "notion_id": "t2",
                                "title": "Prepare weekly report",
                                "url": "",
                                "created_time": "2026-02-02T00:00:00Z",
                                "last_edited_time": "2026-02-09T00:00:00Z",
                                "fields": {
                                    "status": "Todo",
                                    "priority": "High",
                                    "due": "2026-02-20",
                                },
                            },
                        ],
                        "row_count": 2,
                        "last_refreshed_at": "2026-02-10T00:00:00Z",
                        "last_error": None,
                    },
                    "goals": {
                        "db_id": "db_goals",
                        "items": [
                            {
                                "id": "g1",
                                "notion_id": "g1",
                                "title": "Increase conversions",
                                "url": "",
                                "created_time": "2026-01-01T00:00:00Z",
                                "last_edited_time": "2026-02-09T00:00:00Z",
                                "fields": {"status": "Active", "progress": 0.4},
                            }
                        ],
                        "row_count": 1,
                        "last_refreshed_at": "2026-02-10T00:00:00Z",
                        "last_error": None,
                    },
                    "projects": {
                        "db_id": "db_projects",
                        "items": [
                            {
                                "id": "p1",
                                "notion_id": "p1",
                                "title": "Website revamp",
                                "url": "",
                                "created_time": "2026-01-15T00:00:00Z",
                                "last_edited_time": "2026-02-09T00:00:00Z",
                                "fields": {"status": "Active", "priority": "Medium"},
                            }
                        ],
                        "row_count": 1,
                        "last_refreshed_at": "2026-02-10T00:00:00Z",
                        "last_error": None,
                    },
                },
            },
            "meta": {"ok": True, "synced_at": "2026-02-10T00:00:00Z", "errors": []},
        }
    )

    out = await execute(
        "read_only.query",
        {"action": "read_only.query", "query": "ops.daily_brief"},
        agent_id="dept_ops",
        execution_id="exec_test_2",
    )

    assert isinstance(out, dict)
    assert out.get("ok") is True
    assert out.get("execution_state") == "COMPLETED"
    assert isinstance(out.get("data"), dict)
    assert out["data"].get("kind") == "ops.daily_brief"
    assert isinstance(out["data"].get("summary"), dict)
    assert isinstance(out["data"].get("tasks"), dict)
    assert isinstance(out["data"].get("goals"), dict)
    assert isinstance(out["data"].get("projects"), dict)
    assert isinstance(out["data"].get("approvals"), dict)
    assert isinstance(out["data"].get("recommendations"), list)

    counts = out["data"].get("summary", {}).get("counts")
    assert isinstance(counts, dict)
    assert counts.get("open_tasks") == 2
    assert counts.get("active_goals") == 1
    assert counts.get("active_projects") == 1

    # Caps: top_urgent is capped.
    top = out["data"].get("tasks", {}).get("top_urgent")
    assert isinstance(top, list)
    assert len(top) <= 5
    assert isinstance(out.get("meta"), dict)
    assert out["meta"].get("query") == "ops.daily_brief"


@pytest.mark.anyio
async def test_read_only_query_ops_kpi_weekly_preview_is_deterministic() -> None:
    from services.tool_runtime_executor import execute

    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    KnowledgeSnapshotService.update_snapshot(
        {
            "payload": {
                "last_sync": "2026-02-10T00:00:00Z",
                "databases": {
                    "kpi": {
                        "db_id": "db_kpi",
                        "items": [
                            {
                                "id": "k2",
                                "notion_id": "k2",
                                "title": "Week 06",
                                "url": "",
                                "created_time": "2026-02-10T00:00:00Z",
                                "last_edited_time": "2026-02-10T00:00:00Z",
                                "fields": {
                                    "period": "2026-W06",
                                    "outreach": 120,
                                    "conversionscount": 12,
                                    "revenue": 5000,
                                },
                            },
                            {
                                "id": "k1",
                                "notion_id": "k1",
                                "title": "Week 05",
                                "url": "",
                                "created_time": "2026-02-03T00:00:00Z",
                                "last_edited_time": "2026-02-03T00:00:00Z",
                                "fields": {
                                    "period": "2026-W05",
                                    "outreach": 100,
                                    "conversionscount": 10,
                                    "revenue": 4500,
                                },
                            },
                        ],
                        "row_count": 2,
                        "last_refreshed_at": "2026-02-10T00:00:00Z",
                        "last_error": None,
                    }
                },
            },
            "meta": {"ok": True, "synced_at": "2026-02-10T00:00:00Z", "errors": []},
        }
    )

    out = await execute(
        "read_only.query",
        {"action": "read_only.query", "query": "ops.kpi_weekly_summary_preview"},
        agent_id="dept_ops",
        execution_id="exec_test_3",
    )

    assert isinstance(out, dict)
    assert out.get("ok") is True
    assert out.get("execution_state") == "COMPLETED"
    assert isinstance(out.get("data"), dict)
    assert out["data"].get("kind") == "ops.kpi_weekly_summary_preview"
    assert isinstance(out["data"].get("metrics"), list)
    assert isinstance(out["data"].get("periods"), dict)
    metrics = out["data"].get("metrics")
    assert any(m.get("trend") in {"up", "down", "flat"} for m in (metrics or []))
    assert isinstance(out.get("meta"), dict)
    assert out["meta"].get("query") == "ops.kpi_weekly_summary_preview"


@pytest.mark.anyio
async def test_kpi_weekly_preview_reports_missing_reason_when_no_numeric_fields() -> None:
    from services.tool_runtime_executor import execute
    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    KnowledgeSnapshotService.update_snapshot(
        {
            "payload": {
                "last_sync": "2026-02-10T00:00:00Z",
                "databases": {
                    "kpi": {
                        "db_id": "db_kpi",
                        "items": [
                            {
                                "id": "k1",
                                "notion_id": "k1",
                                "title": "Week 05",
                                "url": "",
                                "created_time": "2026-02-03T00:00:00Z",
                                "last_edited_time": "2026-02-03T00:00:00Z",
                                "fields": {"period": "2026-W05"},
                            }
                        ],
                        "row_count": 1,
                        "last_refreshed_at": "2026-02-10T00:00:00Z",
                        "last_error": None,
                    }
                },
            },
            "meta": {"ok": True, "synced_at": "2026-02-10T00:00:00Z", "errors": []},
        }
    )

    out = await execute(
        "read_only.query",
        {"action": "read_only.query", "query": "ops.kpi_weekly_summary_preview"},
        agent_id="dept_ops",
        execution_id="exec_test_kpi_missing",
    )

    assert out["data"].get("kind") == "ops.kpi_weekly_summary_preview"
    assert out["data"].get("missing_reason") == "no_numeric_kpi_fields_in_snapshot"


@pytest.mark.anyio
async def test_read_only_query_ops_caps_are_enforced() -> None:
    from services.tool_runtime_executor import execute
    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    many_tasks = []
    for i in range(30):
        many_tasks.append(
            {
                "id": f"t{i}",
                "notion_id": f"t{i}",
                "title": f"Task {i:02d}",
                "url": "",
                "created_time": "2026-02-01T00:00:00Z",
                "last_edited_time": "2026-02-09T00:00:00Z",
                "fields": {"status": "Todo", "priority": "Urgent" if i < 20 else "Low"},
            }
        )

    KnowledgeSnapshotService.update_snapshot(
        {
            "payload": {
                "last_sync": "2026-02-10T00:00:00Z",
                "databases": {
                    "tasks": {
                        "db_id": "db_tasks",
                        "items": many_tasks,
                        "row_count": len(many_tasks),
                        "last_refreshed_at": "2026-02-10T00:00:00Z",
                        "last_error": None,
                    }
                },
            },
            "meta": {"ok": True, "synced_at": "2026-02-10T00:00:00Z", "errors": []},
        }
    )

    out = await execute(
        "read_only.query",
        {"action": "read_only.query", "query": "ops.daily_brief"},
        agent_id="dept_ops",
        execution_id="exec_test_caps",
    )

    top = out.get("data", {}).get("tasks", {}).get("top_urgent")
    assert isinstance(top, list)
    # top_urgent always capped to 5
    assert len(top) == 5
