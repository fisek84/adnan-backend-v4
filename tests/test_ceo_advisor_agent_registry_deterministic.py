from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_ceo_advisor_lists_agents_deterministically_without_llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "assistants")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    # Even if LLM is configured, this intent must not invoke it.
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: True)

    def _boom(*args, **kwargs):  # pragma: no cover
        raise AssertionError(
            "LLM executor must NOT be called for agent registry questions"
        )

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    from models.agent_contract import AgentInput
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Koje agente imamo",
                snapshot={},
                metadata={},
                preferred_agent_id="ceo_advisor",
            ),
            ctx={},
        )
    )

    assert "agent_id" in (out.text or "")
    assert "ceo_advisor" in (out.text or "")
    assert "revenue_growth_operator" in (out.text or "")
    assert out.trace.get("intent") == "agent_registry"
    assert out.trace.get("exit_reason") == "deterministic.agent_registry"
    assert out.proposed_commands == []


def test_ceo_advisor_lists_agents_even_when_kb_hits_exist_and_llm_offline(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "assistants")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    # Offline: would normally return KB snippets if kb_hits>0.
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: False)

    from models.agent_contract import AgentInput
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Koje agente imamo",
                snapshot={},
                metadata={},
                preferred_agent_id="ceo_advisor",
            ),
            ctx={
                "kb": {
                    "used_entry_ids": ["kb_test_001"],
                    "entries": [
                        {
                            "id": "kb_test_001",
                            "title": "KB entry about agents",
                            "content": "This should NOT be returned; registry list should win.",
                        }
                    ],
                }
            },
        )
    )

    assert out.trace.get("intent") == "agent_registry"
    assert "Evo izvučenih KB snippeta" not in (out.text or "")
    assert "revenue_growth_operator" in (out.text or "")
