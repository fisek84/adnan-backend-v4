from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from models.ai_command import AICommand


@pytest.mark.anyio
async def test_agent_handoff_logged_via_notion_ops_missing_seam(monkeypatch) -> None:
    """Operational requirement: agent handoff/completion logging triggers a notion_ops write request.

    If no such seam exists yet, this test MUST FAIL with:
      "handoff logging path missing"
    and include file:line evidence of what exists today.
    """

    # Avoid real NotionService construction during orchestrator init.
    import services.execution_orchestrator as eo

    monkeypatch.setattr(eo, "get_notion_service", lambda: object())

    orch = eo.ExecutionOrchestrator()

    # Mock notion_ops execution.
    orch.notion_agent.execute = AsyncMock(return_value={"ok": True, "success": True})

    # Use a command that will dispatch to notion_agent.execute in _execute_after_approval.
    cmd = AICommand(
        command="query_database",
        intent="query_database",
        params={"db_key": "kpi", "page_size": 1},
        initiator="system",
        execution_id="exec_test_1",
        approval_id="approval_test_1",
        metadata={"emit_handoff_log": True},
    )

    await orch._execute_after_approval(cmd)

    # Requirement: in addition to executing the command, a handoff/completion record
    # must be written via notion_ops.
    # On the clean tree, there is no second notion_ops call for handoff logging.
    calls = orch.notion_agent.execute.call_count

    assert calls >= 2, (
        "handoff logging path missing\n"
        "Evidence (current behavior): services/execution_orchestrator.py dispatches only once to notion_agent.execute\n"
        "(see the post-approval dispatch block near the workflow/memory_write/else notion_agent.execute)."
    )
