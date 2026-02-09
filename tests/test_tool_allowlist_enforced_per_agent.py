from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from models.ai_command import AICommand


@pytest.mark.anyio
async def test_tool_call_enforces_per_agent_allowlist_and_blocks_without_runtime(
    monkeypatch,
) -> None:
    """tool_call must be allowlisted per agent, and BLOCKED when runtime is missing.

    Repo evidence: there is no tool runtime implementation. Therefore even an
    allowlisted action must return BLOCKED reason=tool_runtime_missing.
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

    # (b) Action IN allowlist (dept_finance has analysis.run) => BLOCKED tool_runtime_missing
    cmd2 = AICommand(
        **{
            **base,
            "execution_id": "exec_test_tool_allowlisted",
            "params": {"action": "analysis.run"},
        }
    )
    res2 = await orch._execute_after_approval(cmd2)
    assert isinstance(res2, dict)
    assert res2.get("execution_state") == "BLOCKED"
    inner2 = res2.get("result")
    assert isinstance(inner2, dict)
    assert inner2.get("reason") == "tool_runtime_missing"
    assert inner2.get("agent_id") == "dept_finance"
    assert inner2.get("action") == "analysis.run"
