from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


def _mk_orchestrator(monkeypatch):
    import services.execution_orchestrator as eo

    monkeypatch.setattr(eo, "get_notion_service", lambda: object())
    orch = eo.ExecutionOrchestrator()
    orch.notion_agent.execute = AsyncMock(
        side_effect=AssertionError("notion_execute_called")
    )
    return orch


@pytest.mark.anyio
async def test_job_runner_blocks_without_approval(monkeypatch) -> None:
    from services.job_runner import JobRunner

    orch = _mk_orchestrator(monkeypatch)
    runner = JobRunner(orchestrator=orch)

    pending = [
        {
            "id": "task_2",
            "status": "pending",
            "role": "finance",
            "command": "tool_call",
            "params": {"action": "analysis.run", "expression": "1 + 2"},
            "approval_id": "",
        }
    ]

    out = await runner.run_pending(pending)
    assert isinstance(out, list) and len(out) == 1

    res = out[0]
    assert isinstance(res, dict)
    assert res.get("execution_state") == "BLOCKED"
    # Governance blocks before tool runtime is invoked.
    assert "result" not in res or res.get("result") in (None, {})
