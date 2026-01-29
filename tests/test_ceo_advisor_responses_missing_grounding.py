import asyncio

from models.agent_contract import AgentInput
from services.ceo_advisor_agent import create_ceo_advisor_agent


def test_ceo_advisor_responses_mode_allows_advisory_without_grounding_pack(monkeypatch):
    # Advisory must never be blocked by missing grounding in Responses mode.
    monkeypatch.setenv("OPENAI_API_KEY", "test_key")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    class _StubExecutor:
        async def ceo_command(self, text, context):
            return {
                "text": "- Korak 1: Definiši cilj\n- Korak 2: Napravi 3 prioriteta\n- Korak 3: Planiraj prvi blok vremena",
                "proposed_commands": [],
            }

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose=None: _StubExecutor(),
    )

    agent_input = AgentInput(
        message="Daj mi kratak plan za danas.",
        identity_pack={"payload": {"role": "ceo"}},
        snapshot={"payload": {"goals": [{"title": "G1"}], "tasks": []}},
        metadata={"session_id": "test_session_responses_guard"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={"grounding_pack": {}}))

    assert out.read_only is True
    assert out.proposed_commands == []
    assert "Ne mogu dati smislen odgovor" not in (out.text or "")
    assert ("\n-" in (out.text or "")) or ("\n1)" in (out.text or ""))
