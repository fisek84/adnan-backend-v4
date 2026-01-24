import asyncio


def test_ceo_advisor_prompt_requires_json_text_field(monkeypatch):
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: True)

    captured = {}

    class DummyExecutor:
        async def ceo_command(self, text, context):
            captured["text"] = text
            return {"text": "ok", "proposed_commands": []}

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose: DummyExecutor(),
    )

    from models.agent_contract import AgentInput
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    asyncio.run(
        create_ceo_advisor_agent(
            AgentInput(message="Koji je glavni grad Francuske?", snapshot={}, metadata={}),
            ctx={},
        )
    )

    prompt = captured.get("text") or ""
    assert "json" in prompt.lower()
    assert "'text'" in prompt or "\"text\"" in prompt
    assert "proposed_commands" in prompt
