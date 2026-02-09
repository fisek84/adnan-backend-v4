from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_job_runner_idempotent_by_job_id(monkeypatch) -> None:
    from services.job_runner import JobRunner

    calls = {"n": 0}

    class _Orch:
        async def execute(self, cmd):  # noqa: ANN001
            calls["n"] += 1
            return {"execution_id": cmd.execution_id, "execution_state": "COMPLETED"}

    runner = JobRunner(orchestrator=_Orch())

    pending = [
        {
            "id": "task_10",
            "status": "pending",
            "role": "finance",
            "command": "tool_call",
            "params": {"action": "analysis.run", "expression": "1 + 2"},
            "approval_id": "appr_10",
        }
    ]

    out1 = await runner.run_pending(pending)
    out2 = await runner.run_pending(pending)

    assert isinstance(out1, list) and len(out1) == 1
    assert isinstance(out2, list) and len(out2) == 1

    # Must not dispatch the same job twice.
    assert calls["n"] == 1

    res2 = out2[0]
    assert isinstance(res2, dict)
    assert res2.get("execution_state") in {"COMPLETED", "SKIPPED"}
    assert isinstance(res2.get("result"), dict)
    assert res2["result"].get("skipped") is True
