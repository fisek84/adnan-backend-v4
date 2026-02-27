import asyncio


def test_approved_delegate_agent_task_routes_to_agent_execution(monkeypatch):
    """Regression: post-approval delegate_agent_task must not route into NotionService.

    Frontend flow:
      - approval created for intent=delegate_agent_task
      - POST /api/ai-ops/approval/approve calls ExecutionOrchestrator.resume(execution_id)

    This test ensures resume() completes successfully and never calls NotionOpsAgent.
    """

    from models.ai_command import AICommand
    from services.execution_orchestrator import ExecutionOrchestrator

    orch = ExecutionOrchestrator()

    # Ensure approval gate passes.
    monkeypatch.setattr(orch.approvals, "is_fully_approved", lambda _aid: True)

    # If NotionOpsAgent is called, the test should fail.
    async def _boom(_cmd):  # noqa: ANN001
        raise RuntimeError("NotionOpsAgent.execute should not be called")

    monkeypatch.setattr(orch.notion_agent, "execute", _boom)

    # Monkeypatch the agent execution pipeline to avoid invoking real agent code.
    async def _fake_delegate(_cmd):  # noqa: ANN001
        return {
            "ok": True,
            "success": True,
            "intent": "delegate_agent_task",
            "result": {"agent_id": "agent_x", "output_text": "hello"},
        }

    monkeypatch.setattr(
        "services.execution_orchestrator._execute_delegate_agent_task_via_router",
        _fake_delegate,
    )

    cmd = AICommand(
        command="delegate_agent_task",
        intent="delegate_agent_task",
        params={"agent_id": "agent_x", "task_text": "Say hello"},
        approval_id="approval_delegate_1",
    )

    # This mimics the approval flow where resume() looks up the command in registry.
    orch.registry.register(cmd)

    res = asyncio.run(orch.resume(cmd.execution_id))

    assert isinstance(res, dict)
    assert res.get("ok") is True
    assert res.get("execution_state") == "COMPLETED"
    assert res.get("execution_id") == cmd.execution_id
    assert res.get("approval_id") == "approval_delegate_1"

    inner = res.get("result")
    assert isinstance(inner, dict)
    assert inner.get("agent_id") == "agent_x"
    assert inner.get("output_text") == "hello"
