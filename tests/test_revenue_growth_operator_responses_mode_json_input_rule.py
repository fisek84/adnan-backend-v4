from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_revenue_growth_operator_responses_mode_includes_json_word(monkeypatch):
    """Regression: Responses API json_object format requires 'json' in request input.

    We keep the fix localized to revenue_growth_operator by ensuring the task.input
    passed into OpenAIResponsesExecutor.execute contains the word 'json'.
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    # Force deterministic env usage (value is irrelevant because we mock execute).
    monkeypatch.setenv("REVENUE_GROWTH_OPERATOR_MODEL", "gpt-test")

    from models.agent_contract import AgentInput
    from services.revenue_growth_operator_agent import revenue_growth_operator_agent

    captured = {}

    async def _fake_execute(self, task):  # noqa: ANN001
        captured["task"] = task
        # Emulate provider validation: fail if 'json' is missing.
        user_input = task.get("input")
        assert isinstance(user_input, str)
        assert "json" in user_input.lower()
        return {"agent": "revenue_growth_operator", "work_done": []}

    monkeypatch.setattr(
        "services.agent_router.openai_responses_executor.OpenAIResponsesExecutor.execute",
        _fake_execute,
        raising=True,
    )

    agent_input = AgentInput(
        message="Draft 3 follow-up emails",
        identity_pack={},
        snapshot={},
        preferred_agent_id="revenue_growth_operator",
        metadata={"read_only": True},
    )

    ctx = {
        "registry_entry": SimpleNamespace(
            metadata={
                "responses_model_env": "REVENUE_GROWTH_OPERATOR_MODEL",
                "read_only": True,
            }
        )
    }

    out = asyncio.run(revenue_growth_operator_agent(agent_input, ctx))
    assert isinstance(out.text, str) and out.text.strip()
    assert captured.get("task") is not None
