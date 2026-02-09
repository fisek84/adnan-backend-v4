from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


def _mk_orchestrator(monkeypatch):
    import services.execution_orchestrator as eo

    monkeypatch.setattr(eo, "get_notion_service", lambda: object())
    orch = eo.ExecutionOrchestrator()
    orch.notion_agent.execute = AsyncMock(return_value={"ok": True})
    return orch


@pytest.mark.anyio
async def test_job_runner_handoff_logged(monkeypatch) -> None:
    from services.job_runner import JobRunner

    orch = _mk_orchestrator(monkeypatch)
    approval = orch.approvals.create(
        command="tool_call",
        payload_summary={"action": "analysis.run"},
        scope="test",
        risk_level="standard",
        execution_id="exec_job_task_4",
    )
    orch.approvals.approve(approval["approval_id"], approved_by="pytest")

    runner = JobRunner(orchestrator=orch)

    pending = [
        {
            "id": "task_4",
            "status": "pending",
            "role": "finance",
            "command": "tool_call",
            "params": {"action": "analysis.run", "expression": "1 + 2"},
            "approval_id": approval["approval_id"],
        }
    ]

    out = await runner.run_pending(pending)
    assert isinstance(out, list) and len(out) == 1
    assert out[0].get("execution_state") == "COMPLETED"

    assert orch.notion_agent.execute.await_count == 1
    called_cmd = orch.notion_agent.execute.await_args.args[0]
    assert getattr(called_cmd, "command", None) == "create_task"
    assert getattr(called_cmd, "approval_id", None) == approval["approval_id"]

    md = getattr(called_cmd, "metadata", None)
    assert isinstance(md, dict)
    assert md.get("handoff_log") is True
