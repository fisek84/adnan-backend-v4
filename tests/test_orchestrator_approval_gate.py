# tests/test_orchestrator_approval_gate.py
from __future__ import annotations

import os
import sys
import asyncio

# --- FIX: ensure project root is on sys.path ---
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.orchestrator.orchestrator_service import OrchestratorService
from services.queue.queue_service import QueueService

import services.approval_state_service as approval_state_service


class _FakeApprovals:
    def __init__(self) -> None:
        self._approved: set[str] = set()

    def approve(self, approval_id: str) -> None:
        self._approved.add(approval_id)

    def is_fully_approved(self, approval_id: str) -> bool:
        return approval_id in self._approved


class _DummyExecutor:
    def execute(self, cmd: dict) -> dict:
        return {
            "ok": True,
            "executed": True,
            "cmd_id": cmd.get("id"),
            "cmd_type": cmd.get("type"),
        }


async def _run() -> None:
    # Patch approval_state_service used by approval_flow.py (lazy import)
    fake = _FakeApprovals()
    approval_state_service.get_approval_state = lambda: fake  # type: ignore[assignment]

    q = QueueService()
    orch = OrchestratorService(q)
    orch._action_executor = _DummyExecutor()  # force deterministic executor

    approval_id = "test-approval-123"

    # CASE A: NOT APPROVED -> blocked
    await orch.submit(
        job_type="agent_execute",
        execution_id="exec_not_approved",
        payload={
            "command": {
                "id": "cmd-1",
                "type": "agent_execute",
                "approval_id": approval_id,
            }
        },
    )
    r1 = await orch.process_once(timeout_seconds=0.1)
    assert (
        isinstance(r1, dict) and r1.get("ok") is False
    ), f"Expected blocked, got: {r1}"
    assert (
        "not approved" in str(r1.get("error", "")).lower()
    ), f"Expected approval error, got: {r1}"

    # CASE B: APPROVED -> allowed
    fake.approve(approval_id)

    await orch.submit(
        job_type="agent_execute",
        execution_id="exec_approved",
        payload={
            "command": {
                "id": "cmd-2",
                "type": "agent_execute",
                "approval_id": approval_id,
            }
        },
    )
    r2 = await orch.process_once(timeout_seconds=0.1)
    assert isinstance(r2, dict) and r2.get("ok") is True, f"Expected success, got: {r2}"
    assert r2.get("executed") is True, f"Expected executed=True, got: {r2}"

    print(
        "TEST PASSED: orchestrator approval gate works (blocked -> approved -> execute)."
    )


if __name__ == "__main__":
    asyncio.run(_run())
