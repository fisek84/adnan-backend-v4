import asyncio

from models.agent_contract import AgentInput
from services.ceo_advisor_agent import create_ceo_advisor_agent


def test_ceo_advisor_responses_mode_blocks_without_grounding_pack(monkeypatch):
    # Make LLM appear "configured" so we reach the Responses-mode grounding guard,
    # but the guard should block before any executor/network path.
    monkeypatch.setenv("OPENAI_API_KEY", "test_key")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    agent_input = AgentInput(
        message="Daj mi kratak plan za danas.",
        identity_pack={"payload": {"role": "ceo"}},
        snapshot={"payload": {"goals": [{"title": "G1"}], "tasks": []}},
        metadata={"session_id": "test_session_responses_guard"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={"grounding_pack": {}}))

    assert out.read_only is True
    assert out.proposed_commands == []
    assert "Ne mogu dati smislen odgovor" in out.text
    assert out.trace.get("exit_reason") == "blocked.missing_grounding"
    assert "used_sources" in out.trace
    assert "missing_inputs" in out.trace
