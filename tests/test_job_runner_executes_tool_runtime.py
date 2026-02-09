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
async def test_job_runner_executes_tool_runtime(monkeypatch) -> None:
    from services.job_runner import JobRunner
    from services.memory_service import MemoryService

    captured: list[dict] = []

    def _capture_audit(self, event: dict) -> None:  # noqa: ANN001
        captured.append(event)

    monkeypatch.setattr(MemoryService, "append_write_audit_event", _capture_audit)

    orch = _mk_orchestrator(monkeypatch)
    # Governance requires an approval_id that is fully approved.
    approval = orch.approvals.create(
        command="tool_call",
        payload_summary={"action": "analysis.run"},
        scope="test",
        risk_level="standard",
        execution_id="exec_job_task_3",
    )
    orch.approvals.approve(approval["approval_id"], approved_by="pytest")

    runner = JobRunner(orchestrator=orch)

    pending = [
        {
            "id": "task_3",
            "status": "pending",
            "role": "finance",
            "command": "tool_call",
            "params": {"action": "analysis.run", "expression": "1 + 2 * 3"},
            "approval_id": approval["approval_id"],
        }
    ]

    out = await runner.run_pending(pending)
    assert isinstance(out, list) and len(out) == 1

    res = out[0]
    assert isinstance(res, dict)
    assert res.get("execution_state") == "COMPLETED"

    assert any(
        isinstance(e, dict)
        and e.get("event_type") == "tool_runtime"
        and e.get("action") == "analysis.run"
        and e.get("agent_id") == "dept_finance"
        for e in captured
    ), "tool runtime audit event missing"
