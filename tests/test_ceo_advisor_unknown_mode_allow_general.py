import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_unknown_mode_does_not_block_llm_when_allow_general_true(monkeypatch):
    """Regression: when allow_general=1 and LLM is configured, unknown_mode gate must not return fallback."""

    # This regression test is for legacy (Assistants-mode) behavior.
    # In Responses mode, LLM calls require grounding_pack-backed instructions.
    monkeypatch.setenv("OPENAI_API_MODE", "assistants")

    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")

    # Force LLM configured.
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: True)

    class DummyExecutor:
        async def ceo_command(self, text, context):
            return {"text": "Glavni grad Francuske je Pariz.", "proposed_commands": []}

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose: DummyExecutor(),
    )

    from models.agent_contract import AgentInput
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Koji je glavni grad Francuske?",
                snapshot={},
                metadata={},
                preferred_agent_id="ceo_advisor",
            ),
            ctx={},
        )
    )

    assert "Pariz" in out.text
    assert out.trace.get("exit_reason") == "llm.success"
    assert out.trace.get("intent") != "unknown_mode"


def test_unknown_mode_fallback_when_allow_general_false(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "assistants")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: True)

    from models.agent_contract import AgentInput
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Koji je glavni grad Francuske?",
                snapshot={},
                metadata={},
                preferred_agent_id="ceo_advisor",
            ),
            ctx={},
        )
    )

    assert "Ne mogu dati smislen odgovor" in out.text
    assert out.trace.get("exit_reason") == "fallback.allow_general_false"
    assert out.trace.get("intent") == "unknown_mode"
