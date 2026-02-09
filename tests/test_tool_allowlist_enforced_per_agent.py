from __future__ import annotations

import pytest

from models.ai_command import AICommand


@pytest.mark.anyio
async def test_tool_call_enforces_per_agent_allowlist_and_blocks_without_runtime(
    monkeypatch,
) -> None:
    """tool_call must be allowlisted per agent.

    - non-allowlisted action => BLOCKED action_not_allowed
    - allowlisted action + approval => executes via tool runtime
    """

    import services.execution_orchestrator as eo

    # Avoid real NotionService construction during orchestrator init.
    monkeypatch.setattr(eo, "get_notion_service", lambda: object())

    orch = eo.ExecutionOrchestrator()

    base = {
        "command": "tool_call",
        "intent": "tool_call",
        "initiator": "system",
        "approval_id": "approval_test_tool_1",
        "metadata": {"agent_id": "dept_finance"},
    }

    # (a) Action NOT in allowlist => BLOCKED action_not_allowed
    cmd1 = AICommand(
        **{
            **base,
            "execution_id": "exec_test_tool_not_allowed",
            "params": {"action": "definitely.not.allowlisted"},
        }
    )
    res1 = await orch._execute_after_approval(cmd1)
    assert isinstance(res1, dict)
    assert res1.get("execution_state") == "BLOCKED"
    inner1 = res1.get("result")
    assert isinstance(inner1, dict)
    assert inner1.get("reason") == "action_not_allowed"
    assert inner1.get("agent_id") == "dept_finance"

    # (b) Action IN allowlist (dept_finance has analysis.run) => executes
    cmd2 = AICommand(
        **{
            **base,
            "execution_id": "exec_test_tool_allowlisted",
            "params": {"action": "analysis.run", "expression": "1 + 2 * 3"},
        }
    )
    res2 = await orch._execute_after_approval(cmd2)
    assert isinstance(res2, dict)
    assert res2.get("execution_state") == "COMPLETED"
    inner2 = res2.get("result")
    assert isinstance(inner2, dict)
    assert inner2.get("ok") is True
    assert inner2.get("agent_id") == "dept_finance"
    assert inner2.get("action") == "analysis.run"
    data2 = inner2.get("data")
    assert isinstance(data2, dict)
    assert data2.get("result") == 7.0
