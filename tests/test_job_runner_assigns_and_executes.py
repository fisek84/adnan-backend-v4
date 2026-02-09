from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_job_runner_assigns_and_executes(monkeypatch) -> None:
    from services.job_runner import JobRunner

    captured = {}

    class _Orch:
        async def execute(self, cmd):  # noqa: ANN001
            captured["cmd"] = cmd
            return {"execution_id": cmd.execution_id, "execution_state": "COMPLETED"}

    runner = JobRunner(orchestrator=_Orch())

    pending = [
        {
            "id": "task_1",
            "status": "pending",
            "role": "finance",
            "command": "tool_call",
            "params": {"action": "analysis.run", "expression": "1 + 2"},
            "approval_id": "appr_1",
        }
    ]

    out = await runner.run_pending(pending)
    assert isinstance(out, list) and out

    cmd = captured.get("cmd")
    assert cmd is not None

    md = cmd.metadata
    assert isinstance(md, dict)
    assert md.get("agent_id") == "dept_finance"
    assert cmd.approval_id == "appr_1"
