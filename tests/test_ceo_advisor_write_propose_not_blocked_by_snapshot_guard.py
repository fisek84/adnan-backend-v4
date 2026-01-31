import asyncio
import os

from models.agent_contract import AgentInput
from services.ceo_advisor_agent import create_ceo_advisor_agent
from services.notion_ops_state import set_armed


def test_write_create_goal_not_blocked_by_fact_sensitive_missing_snapshot_guard():
    os.environ.pop("OPENAI_API_KEY", None)

    session_id = "test_write_goal_no_snapshot_not_blocked"
    asyncio.run(set_armed(session_id, True, prompt="arm for test"))

    agent_input = AgentInput(
        message="Kreiraj cilj: Mjesecni prihod od 5500 BAM, Status active, Priority high",
        identity_pack={"payload": {"role": "ceo"}},
        snapshot={},
        metadata={"session_id": session_id},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={"memory": {"x": 1}}))

    assert any(pc.command == "notion_write" for pc in (out.proposed_commands or []))
    assert "Ne mogu potvrditi poslovno stanje" not in (out.text or "")
    assert all(pc.command != "refresh_snapshot" for pc in (out.proposed_commands or []))
    assert isinstance(out.trace, dict)
    assert out.trace.get("response_class") == "action_propose"
    assert out.trace.get("exit_reason") != "fallback.fact_sensitive_no_snapshot"


def test_fact_status_query_without_snapshot_still_hits_fact_sensitive_fallback():
    os.environ.pop("OPENAI_API_KEY", None)

    session_id = "test_fact_query_no_snapshot_still_blocked"
    asyncio.run(set_armed(session_id, True, prompt="arm for test"))

    agent_input = AgentInput(
        message="Koji je status mojih ciljeva?",
        identity_pack={"payload": {"role": "ceo"}},
        snapshot={},
        metadata={"session_id": session_id},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={"memory": {"x": 1}}))

    assert "Ne mogu potvrditi poslovno stanje" in (out.text or "")
    assert any(pc.command == "refresh_snapshot" for pc in (out.proposed_commands or []))
    assert all(pc.command != "notion_write" for pc in (out.proposed_commands or []))
