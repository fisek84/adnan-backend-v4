from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


def _mk_orchestrator(monkeypatch):
    import services.execution_orchestrator as eo

    # Avoid real Notion ops in tests.
    monkeypatch.setattr(eo, "get_notion_service", lambda: object())
    orch = eo.ExecutionOrchestrator()
    orch.notion_agent.execute = AsyncMock(
        side_effect=AssertionError("notion_execute_called")
    )
    return orch


@pytest.mark.anyio
async def test_run_template_fin_pending_then_executes(monkeypatch) -> None:
    from services.audit_service import AuditService
    from services.job_runner import JobRunner
    from services.memory_service import MemoryService

    orch = _mk_orchestrator(monkeypatch)
    runner = JobRunner(orchestrator=orch)

    job_id = f"job_fin_{uuid4().hex}"

    # Baseline audit count (derived from approvals fallback).
    audit0 = AuditService().get_execution_audit().get("api_execute_raw:tool_call") or {}
    total0 = int(audit0.get("total", 0))

    captured: list[dict] = []

    def _capture_audit(self, event: dict) -> None:  # noqa: ANN001
        captured.append(event)

    monkeypatch.setattr(MemoryService, "append_write_audit_event", _capture_audit)

    out1 = await runner.run_template(
        "JT-FIN-01",
        inputs={"expression": "1 + 2 * 3"},
        initiator="system",
        job_id=job_id,
    )

    assert out1.get("execution_state") == "BLOCKED"
    pending = out1.get("pending_approvals")
    assert isinstance(pending, list) and len(pending) == 1
    approval_id = pending[0].get("approval_id")
    assert isinstance(approval_id, str) and approval_id.strip()

    # Idempotency: replay should return the same approval_id (no double enqueue).
    out1b = await runner.run_template(
        "JT-FIN-01",
        inputs={"expression": "1 + 2 * 3"},
        initiator="system",
        job_id=job_id,
    )
    pending_b = out1b.get("pending_approvals")
    assert isinstance(pending_b, list) and len(pending_b) == 1
    assert pending_b[0].get("approval_id") == approval_id

    audit1 = AuditService().get_execution_audit().get("api_execute_raw:tool_call") or {}
    total1 = int(audit1.get("total", 0))
    assert total1 >= total0 + 1

    orch.approvals.approve(approval_id, approved_by="pytest")

    out2 = await runner.run_template(
        "JT-FIN-01",
        inputs={"expression": "1 + 2 * 3", "approval_id": approval_id},
        initiator="system",
        job_id=job_id,
    )

    assert out2.get("execution_state") == "COMPLETED"
    steps = out2.get("steps")
    assert isinstance(steps, list) and len(steps) == 1
    step0 = steps[0]
    assert step0.get("execution_state") == "COMPLETED"
    result0 = step0.get("result")
    assert isinstance(result0, dict)
    assert result0.get("action") == "analysis.run"
    assert isinstance(result0.get("data"), dict)
    assert result0["data"].get("result") == 7.0

    assert any(
        isinstance(e, dict)
        and e.get("event_type") == "tool_runtime"
        and e.get("action") == "analysis.run"
        and e.get("agent_id") == "dept_finance"
        for e in captured
    ), "tool runtime audit event missing"


@pytest.mark.anyio
async def test_run_template_prod_pending_then_executes(monkeypatch) -> None:
    from services.audit_service import AuditService
    from services.job_runner import JobRunner

    orch = _mk_orchestrator(monkeypatch)
    runner = JobRunner(orchestrator=orch)

    job_id = f"job_prod_{uuid4().hex}"

    audit0 = AuditService().get_execution_audit().get("api_execute_raw:tool_call") or {}
    total0 = int(audit0.get("total", 0))

    out1 = await runner.run_template(
        "JT-PROD-01",
        inputs={
            "title": "Checkout flow",
            "problem": "Too many steps",
            "description": "Break down tasks",
        },
        initiator="system",
        job_id=job_id,
    )

    assert out1.get("execution_state") == "BLOCKED"
    pending = out1.get("pending_approvals")
    assert isinstance(pending, list) and len(pending) == 2

    approvals_by_step = {
        str(p.get("step_id")): str(p.get("approval_id")) for p in pending
    }
    assert all(v.strip() for v in approvals_by_step.values())

    audit1 = AuditService().get_execution_audit().get("api_execute_raw:tool_call") or {}
    total1 = int(audit1.get("total", 0))
    assert total1 >= total0 + 2

    for aid in approvals_by_step.values():
        orch.approvals.approve(aid, approved_by="pytest")

    out2 = await runner.run_template(
        "JT-PROD-01",
        inputs={
            "title": "Checkout flow",
            "problem": "Too many steps",
            "description": "Break down tasks",
            "approval_ids": approvals_by_step,
        },
        initiator="system",
        job_id=job_id,
    )

    assert out2.get("execution_state") == "COMPLETED"
    steps = out2.get("steps")
    assert isinstance(steps, list) and len(steps) == 2
    assert steps[0].get("execution_state") == "COMPLETED"
    assert steps[1].get("execution_state") == "COMPLETED"

    r0 = steps[0].get("result")
    r1 = steps[1].get("result")
    assert isinstance(r0, dict) and r0.get("action") == "draft.spec"
    assert isinstance(r1, dict) and r1.get("action") == "draft.issue"


@pytest.mark.anyio
async def test_run_template_planned_tool_blocks_tool_not_executable(monkeypatch, tmp_path: Path) -> None:
    from services.job_runner import JobRunner

    # Create a minimal template that references a planned tool.
    planned_templates = {
        "version": "1.0",
        "job_templates": [
            {
                "id": "JT-PLAN-01",
                "title": "Planned email.read must never execute",
                "role": "growth",
                "steps": [
                    {
                        "tool_action": "email.read",
                        "requires_approval": True,
                        "params_schema": {},
                    }
                ],
                "expected_outputs": [],
            }
        ],
    }

    p = tmp_path / "job_templates_planned.json"
    p.write_text(json.dumps(planned_templates), encoding="utf-8")

    monkeypatch.setenv("JOB_TEMPLATES_JSON_PATH", str(p))

    orch = _mk_orchestrator(monkeypatch)
    runner = JobRunner(orchestrator=orch)

    job_id = f"job_plan_{uuid4().hex}"

    out1 = await runner.run_template(
        "JT-PLAN-01",
        inputs={},
        initiator="system",
        job_id=job_id,
    )

    assert out1.get("execution_state") == "BLOCKED"
    pending = out1.get("pending_approvals")
    assert isinstance(pending, list) and len(pending) == 1
    approval_id = str(pending[0].get("approval_id"))
    assert approval_id.strip()

    orch.approvals.approve(approval_id, approved_by="pytest")

    out2 = await runner.run_template(
        "JT-PLAN-01",
        inputs={"approval_id": approval_id},
        initiator="system",
        job_id=job_id,
    )

    assert out2.get("execution_state") == "BLOCKED"
    steps = out2.get("steps")
    assert isinstance(steps, list) and len(steps) == 1
    step0 = steps[0]
    assert step0.get("execution_state") == "BLOCKED"
    inner = step0.get("result")
    assert isinstance(inner, dict)
    assert inner.get("reason") == "tool_not_executable"
