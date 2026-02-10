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
    brief = out["data"].get("brief")
    assert isinstance(brief, dict)
    assert isinstance(brief.get("highlights"), list)
    assert isinstance(brief.get("next_actions"), list)
    assert isinstance(out.get("meta"), dict)
    assert out["meta"].get("query") == "ops.daily_brief"


@pytest.mark.anyio
async def test_read_only_query_ops_kpi_weekly_preview_is_deterministic() -> None:
    from services.tool_runtime_executor import execute

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
    assert isinstance(out.get("meta"), dict)
    assert out["meta"].get("query") == "ops.kpi_weekly_summary_preview"
