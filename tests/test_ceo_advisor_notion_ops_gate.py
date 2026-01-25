import asyncio
import os

from models.agent_contract import AgentInput
from services.ceo_advisor_agent import create_ceo_advisor_agent
from services.notion_ops_state import set_armed


def test_ceo_advisor_strips_write_proposals_when_notion_ops_disarmed():
    os.environ.pop("OPENAI_API_KEY", None)

    session_id = "test_session_notion_ops_disarmed"
    asyncio.run(set_armed(session_id, False, prompt="test"))

    agent_input = AgentInput(
        message="napravi sedmicni plan prioriteta",
        identity_pack={"payload": {"role": "ceo"}},
        snapshot={
            "payload": {
                "tasks": [],
                "goals": [{"title": "G1"}],
                "projects": [],
            }
        },
        metadata={"session_id": session_id},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={"memory": {"x": 1}}))

    assert out.read_only is True
    assert out.proposed_commands == []
    assert isinstance(out.trace, dict)
    assert out.trace.get("notion_ops_gate", {}).get("applied") is True


def test_ceo_advisor_allows_write_proposals_when_notion_ops_armed():
    os.environ.pop("OPENAI_API_KEY", None)

    session_id = "test_session_notion_ops_armed"
    asyncio.run(set_armed(session_id, True, prompt="test"))

    agent_input = AgentInput(
        message="napravi sedmicni plan prioriteta",
        identity_pack={"payload": {"role": "ceo"}},
        snapshot={
            "payload": {
                "tasks": [],
                "goals": [{"title": "G1"}],
                "projects": [],
            }
        },
        metadata={"session_id": session_id},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={"memory": {"x": 1}}))

    assert out.read_only is True
    assert len(out.proposed_commands) == 1
    assert out.proposed_commands[0].command == "notion_write"
    assert isinstance(out.trace, dict)
    assert out.trace.get("notion_ops", {}).get("armed") is True
