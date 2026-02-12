from __future__ import annotations

import json
import os

import pytest

from models.agent_contract import AgentInput, AgentOutput
from services.revenue_growth_operator_agent import revenue_growth_operator_agent


@pytest.mark.anyio
async def test_revenue_growth_operator_disables_tools_and_emits_no_proposed_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_execute(payload):
        # Enforce governance knobs.
        assert isinstance(payload, dict)
        assert payload.get("allow_tools") is False
        assert payload.get("temperature") == 0
        assert isinstance(payload.get("instructions"), str)
        assert isinstance(payload.get("input"), str)

        calls["payload"] = payload

        # Return a valid contract-like dict.
        return {
            "agent": "revenue_growth_operator",
            "objective": "test-objective",
            "work_done": [
                {
                    "type": "email_draft",
                    "content": "Draft email body",
                    "meta": {"role_intent": "sales_operator"},
                }
            ],
            "next_steps": ["CEO to approve draft"],
            "recommendations_to_ceo": [],
            "requests_from_ceo": [],
            # Even if model tries to propose, AgentOutput.proposed_commands must remain empty.
            "notion_ops_proposal": [
                {
                    "command": "create_task",
                    "args": {"title": "Should not auto-execute"},
                    "reason": "proposal-only",
                    "dry_run": False,
                    "requires_approval": False,
                }
            ],
        }

    class _FakeResponsesExecutor:
        def __init__(self, model_env: str):
            self.model_env = model_env

        async def execute(self, payload):
            return await _fake_execute(payload)

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setattr(
        "services.revenue_growth_operator_agent.OpenAIResponsesExecutor",
        _FakeResponsesExecutor,
        raising=True,
    )

    out = await revenue_growth_operator_agent(
        AgentInput(message="Increase revenue", metadata={"read_only": True}),
        ctx={
            "registry_entry": type(
                "E",
                (),
                {"metadata": {"responses_model_env": "REVENUE_GROWTH_OPERATOR_MODEL"}},
            )(),
        },
    )

    assert isinstance(out, AgentOutput)
    assert out.agent_id == "revenue_growth_operator"
    assert out.read_only is True
    assert out.proposed_commands == []

    parsed = json.loads(out.text)
    assert isinstance(parsed, dict)
    assert parsed.get("agent") == "revenue_growth_operator"
    assert isinstance(parsed.get("work_done"), list)

    tr = out.trace
    assert isinstance(tr, dict)
    assert tr.get("no_tools") is True


@pytest.mark.anyio
async def test_revenue_growth_operator_assistants_mode_requires_env_binding_when_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This ensures we never silently hardcode assistant IDs.
    monkeypatch.delenv("REVENUE_GROWTH_OPERATOR_ASSISTANT_ID", raising=False)
    monkeypatch.setenv("OPENAI_API_MODE", "assistants")

    out = await revenue_growth_operator_agent(
        AgentInput(message="Test", metadata={"read_only": True}),
        ctx={
            "registry_entry": type(
                "E",
                (),
                {"metadata": {"assistant_id": "ENV:REVENUE_GROWTH_OPERATOR_ASSISTANT_ID"}},
            )(),
        },
    )

    # Must fail soft into requests_from_ceo without raising.
    parsed = json.loads(out.text)
    assert isinstance(parsed, dict)
    assert parsed.get("agent") == "revenue_growth_operator"
    assert isinstance(parsed.get("requests_from_ceo"), list)
