from __future__ import annotations

import asyncio

import pytest


@pytest.mark.anyio
async def test_job_runner_respects_concurrency_limit() -> None:
    from services.job_runner import JobRunner

    state = {"in_flight": 0, "max": 0}
    release = asyncio.Event()
    started_two = asyncio.Event()

    class _Orch:
        async def execute(self, cmd):  # noqa: ANN001
            state["in_flight"] += 1
            state["max"] = max(state["max"], state["in_flight"])
            if state["max"] >= 2:
                started_two.set()
            await release.wait()
            state["in_flight"] -= 1
            return {"execution_id": cmd.execution_id, "execution_state": "COMPLETED"}

    runner = JobRunner(orchestrator=_Orch(), max_concurrency=2)

    pending = [
        {
            "id": f"task_c_{i}",
            "status": "pending",
            "role": "finance",
            "command": "tool_call",
            "params": {"action": "analysis.run", "expression": "1 + 2"},
            "approval_id": f"appr_c_{i}",
        }
        for i in range(5)
    ]

    task = asyncio.create_task(runner.run_pending(pending))
    await asyncio.wait_for(started_two.wait(), timeout=2.0)
    release.set()

    out = await asyncio.wait_for(task, timeout=2.0)
    assert isinstance(out, list) and len(out) == 5
    assert state["max"] <= 2


@pytest.mark.anyio
async def test_job_runner_retries_with_deterministic_backoff(monkeypatch) -> None:
    from services.job_runner import JobRunner

    attempts = {"n": 0}

    class _Orch:
        async def execute(self, cmd):  # noqa: ANN001
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("transient")
            return {"execution_id": cmd.execution_id, "execution_state": "COMPLETED"}

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(float(seconds))

    import services.job_runner as jr

    monkeypatch.setattr(jr.asyncio, "sleep", _fake_sleep)

    runner = JobRunner(
        orchestrator=_Orch(),
        max_concurrency=1,
        max_retries=2,
        backoff_base_seconds=0.01,
    )

    pending = [
        {
            "id": "task_r_1",
            "status": "pending",
            "role": "finance",
            "command": "tool_call",
            "params": {"action": "analysis.run", "expression": "1 + 2"},
            "approval_id": "appr_r_1",
        }
    ]

    out = await runner.run_pending(pending)
    assert isinstance(out, list) and len(out) == 1
    assert attempts["n"] == 3
    assert sleep_calls == [0.01, 0.02]
