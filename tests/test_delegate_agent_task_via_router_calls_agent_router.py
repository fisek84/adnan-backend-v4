import asyncio


def test_execute_delegate_agent_task_via_router_calls_agent_router(monkeypatch):
    """Regression: _execute_delegate_agent_task_via_router must call AgentRouterService.route.

    This is the backend proof that post-approval delegate_agent_task uses the existing
    agent runtime (AgentRegistryService + AgentRouterService), not NotionOps.
    """

    from models.ai_command import AICommand
    from models.agent_contract import AgentOutput
    from services.execution_orchestrator import _execute_delegate_agent_task_via_router

    calls = []

    async def _fake_route(self, agent_input):  # noqa: ANN001
        calls.append(agent_input)
        return AgentOutput(
            text="TEST OK",
            proposed_commands=[],
            agent_id=str(getattr(agent_input, "preferred_agent_id", "") or ""),
            read_only=True,
            trace={"via": "fake_route"},
        )

    monkeypatch.setattr(
        "services.agent_router_service.AgentRouterService.route",
        _fake_route,
        raising=True,
    )

    cmd = AICommand(
        command="delegate_agent_task",
        intent="delegate_agent_task",
        params={"agent_id": "dept_finance", "task_text": "Say hi"},
        approval_id="approval_delegate_router_calls_1",
    )

    res = asyncio.run(_execute_delegate_agent_task_via_router(cmd))

    assert isinstance(res, dict)
    assert res.get("ok") is True

    inner = res.get("result")
    assert isinstance(inner, dict)
    assert inner.get("agent_id") == "dept_finance"
    assert inner.get("output_text") == "TEST OK"

    tr = inner.get("trace")
    assert isinstance(tr, dict)
    assert tr.get("via") == "fake_route"

    assert len(calls) == 1
    assert getattr(calls[0], "preferred_agent_id", None) == "dept_finance"
