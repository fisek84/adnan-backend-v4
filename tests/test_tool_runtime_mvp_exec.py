from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from models.ai_command import AICommand


def _mk_orchestrator(monkeypatch):
    import services.execution_orchestrator as eo

    # Avoid real NotionService construction during orchestrator init.
    monkeypatch.setattr(eo, "get_notion_service", lambda: object())

    orch = eo.ExecutionOrchestrator()

    # Guardrail: tool runtime must never dispatch to NotionOpsAgent.
    orch.notion_agent.execute = AsyncMock(
        side_effect=AssertionError("notion_execute_called")
    )
    return orch


@pytest.mark.anyio
async def test_tool_call_blocks_without_approval(monkeypatch) -> None:
    orch = _mk_orchestrator(monkeypatch)

    cmd = AICommand(
        command="tool_call",
        intent="tool_call",
        params={"action": "read_only.query", "query": "kpi"},
        initiator="system",
        execution_id="exec_tool_no_approval",
        approval_id="",
        metadata={"agent_id": "dept_finance"},
    )

    res = await orch._execute_after_approval(cmd)
    assert isinstance(res, dict)
    assert res.get("execution_state") == "BLOCKED"

    inner = res.get("result")
    assert isinstance(inner, dict)
    assert inner.get("reason") in {"approval_required", "approval_id_required"}


@pytest.mark.anyio
async def test_tool_call_executes_allowlisted_readonly_tool_with_approval(
    monkeypatch,
) -> None:
    from services.memory_service import MemoryService

    captured: list[dict] = []

    def _capture_audit(self, event: dict) -> None:  # noqa: ANN001
        captured.append(event)

    monkeypatch.setattr(MemoryService, "append_write_audit_event", _capture_audit)

    orch = _mk_orchestrator(monkeypatch)

    cmd = AICommand(
        command="tool_call",
        intent="tool_call",
        params={"action": "read_only.query", "query": "kpi"},
        initiator="system",
        execution_id="exec_tool_readonly",
        approval_id="approval_test_1",
        metadata={"agent_id": "dept_finance"},
    )

    res = await orch._execute_after_approval(cmd)
    assert isinstance(res, dict)
    assert res.get("execution_state") == "COMPLETED"

    inner = res.get("result")
    assert isinstance(inner, dict)
    assert inner.get("ok") is True
    assert inner.get("execution_state") == "COMPLETED"
    assert inner.get("action") == "read_only.query"
    assert isinstance(inner.get("data"), dict)

    assert any(
        isinstance(e, dict)
        and e.get("event_type") == "tool_runtime"
        and e.get("action") == "read_only.query"
        and e.get("agent_id") == "dept_finance"
        for e in captured
    ), "tool runtime audit event missing"


@pytest.mark.anyio
async def test_tool_call_blocks_non_allowlisted_action_even_with_approval(
    monkeypatch,
) -> None:
    orch = _mk_orchestrator(monkeypatch)

    cmd = AICommand(
        command="tool_call",
        intent="tool_call",
        params={"action": "gmail.send"},
        initiator="system",
        execution_id="exec_tool_not_allowlisted",
        approval_id="approval_test_2",
        metadata={"agent_id": "dept_finance"},
    )

    res = await orch._execute_after_approval(cmd)
    assert isinstance(res, dict)
    assert res.get("execution_state") == "BLOCKED"

    inner = res.get("result")
    assert isinstance(inner, dict)
    assert inner.get("reason") == "action_not_allowed"


@pytest.mark.anyio
async def test_draft_tools_return_text_and_never_send(monkeypatch) -> None:
    orch = _mk_orchestrator(monkeypatch)

    # If any email/send hook exists, it must not be called.
    try:
        import ext.gmail.sender as gmail_sender  # type: ignore

        monkeypatch.setattr(
            gmail_sender,
            "send_email",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("send_email_called")
            ),
        )
    except Exception:
        # If module doesn't exist, fine.
        pass

    cmd = AICommand(
        command="tool_call",
        intent="tool_call",
        params={
            "action": "draft.outreach",
            "to": "example@company.com",
            "subject": "Hello",
            "context": "short intro",
        },
        initiator="system",
        execution_id="exec_tool_draft_outreach",
        approval_id="approval_test_3",
        metadata={"agent_id": "dept_growth"},
    )

    res = await orch._execute_after_approval(cmd)
    assert isinstance(res, dict)
    assert res.get("execution_state") == "COMPLETED"

    inner = res.get("result")
    assert isinstance(inner, dict)
    out = inner.get("output")
    assert isinstance(out, dict)
    txt = out.get("text")
    assert isinstance(txt, str) and txt.strip()
