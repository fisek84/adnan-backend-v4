from __future__ import annotations

import pytest

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.department_agents import dept_growth_agent


@pytest.mark.anyio
async def test_dept_growth_always_returns_canonical_four_sections_and_normalizes_proposals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _stub_ceo_advisor_agent(*_args, **_kwargs):
        # Simulate a delegated response with unsafe proposal flags.
        return AgentOutput(
            text="delegated",
            proposed_commands=[
                ProposedCommand(
                    command="create_task",
                    args={"title": "x"},
                    reason="test",
                    dry_run=False,
                    requires_approval=False,
                    risk="LOW",
                )
            ],
            agent_id="ceo_advisor",
            read_only=True,
            trace={},
        )

    monkeypatch.setattr(
        "services.department_agents.create_ceo_advisor_agent",
        _stub_ceo_advisor_agent,
        raising=True,
    )

    out = await dept_growth_agent(
        AgentInput(message="hello", metadata={"read_only": True}),
        ctx={},
    )

    assert isinstance(out, AgentOutput)
    assert out.agent_id == "dept_growth"

    # Canonical 4-section format must always be present.
    text = out.text or ""
    assert "Summary\n" in text
    assert "Evidence\n" in text
    assert "Recommendation\n" in text
    assert "Proposed Actions\n" in text

    # Dept contract: always approval-gated + dry_run.
    assert isinstance(out.proposed_commands, list)
    assert len(out.proposed_commands) == 1
    pc = out.proposed_commands[0]
    assert getattr(pc, "dry_run", None) is True
    assert getattr(pc, "requires_approval", None) is True


@pytest.mark.anyio
async def test_dept_growth_orchestrator_allows_only_draft_outreach_execution(monkeypatch):
    import services.execution_orchestrator as eo

    # Avoid real NotionService construction during orchestrator init.
    monkeypatch.setattr(eo, "get_notion_service", lambda: object())

    from models.ai_command import AICommand

    orch = eo.ExecutionOrchestrator()

    base = {
        "command": "tool_call",
        "intent": "tool_call",
        "initiator": "system",
        "approval_id": "approval_test_growth_1",
        "metadata": {"agent_id": "dept_growth"},
    }

    # Allowed: draft.outreach (mvp_executable)
    cmd_ok = AICommand(
        **{
            **base,
            "execution_id": "exec_growth_draft_outreach",
            "params": {"action": "draft.outreach", "to": "a@b.com", "subject": "Hi"},
        }
    )
    res_ok = await orch._execute_after_approval(cmd_ok)
    assert isinstance(res_ok, dict)
    assert res_ok.get("execution_state") == "COMPLETED"
    inner_ok = res_ok.get("result")
    assert isinstance(inner_ok, dict)
    assert inner_ok.get("ok") is True
    assert inner_ok.get("action") == "draft.outreach"
    out_ok = inner_ok.get("output")
    assert isinstance(out_ok, dict)
    assert "Subject:" in str(out_ok.get("text") or "")

    # Disallowed (planned tool, not executable): email.send
    cmd_block = AICommand(
        **{
            **base,
            "execution_id": "exec_growth_email_send",
            "params": {"action": "email.send", "to": "a@b.com"},
        }
    )
    res_block = await orch._execute_after_approval(cmd_block)
    assert isinstance(res_block, dict)
    assert res_block.get("execution_state") == "BLOCKED"
    inner_block = res_block.get("result")
    assert isinstance(inner_block, dict)
    assert inner_block.get("action") == "email.send"
    assert inner_block.get("reason") in {
        "tool_not_executable",
        "action_not_allowed",
        "tool_unknown",
    }
