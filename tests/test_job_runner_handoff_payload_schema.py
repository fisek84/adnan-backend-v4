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
async def test_job_runner_handoff_payload_schema(monkeypatch) -> None:
    from services.job_runner import JobRunner

    orch = _mk_orchestrator(monkeypatch)
    approval = orch.approvals.create(
        command="tool_call",
        payload_summary={"action": "analysis.run"},
        scope="test",
        risk_level="standard",
        execution_id="exec_job_task_schema_1",
    )
    orch.approvals.approve(approval["approval_id"], approved_by="pytest")

    runner = JobRunner(orchestrator=orch)

    pending = [
        {
            "id": "task_schema_1",
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

    params = getattr(called_cmd, "params", None)
    assert isinstance(params, dict)

    # Standardized handoff payload must be present on the write request.
    payload = params.get("handoff")
    assert isinstance(payload, dict)

    for k in ("job_id", "agent_id", "execution_id", "state", "summary"):
        assert k in payload

    assert payload["job_id"] == "task_schema_1"
    assert payload["agent_id"] == "dept_finance"
    assert payload["execution_id"] == "exec_job_task_schema_1"
    assert payload["state"] == "COMPLETED"
    assert isinstance(payload["summary"], str) and payload["summary"].strip()
