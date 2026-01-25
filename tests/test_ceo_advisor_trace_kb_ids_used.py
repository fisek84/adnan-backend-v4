from __future__ import annotations

from typing import Any, Dict

import asyncio

from models.agent_contract import AgentInput


def test_ceo_advisor_emits_kb_ids_used_in_trace(monkeypatch):
    import services.ceo_advisor_agent as agent

    # Make sure we don't accidentally call any real executor.
    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    inp = AgentInput(
        message="Možeš li objasniti kako radi memorija?",  # triggers deterministic memory capability path
        snapshot={"payload": {"goals": [], "tasks": [], "projects": []}},
        identity_pack={"schema_version": "identity_pack.v1", "identity": {"name": "Adnan"}},
        metadata={"session_id": "t-1"},
    )

    ctx: Dict[str, Any] = {
        "grounding_pack": {
            "enabled": True,
            "kb_retrieved": {
                "used_entry_ids": ["kb_a", "kb_b"],
                "entries": [
                    {"id": "kb_a", "title": "A", "content": "..."},
                    {"id": "kb_b", "title": "B", "content": "..."},
                ],
            },
            "memory_snapshot": {"payload": {"notes": []}},
            "notion_snapshot": {"payload": {"goals": [], "tasks": [], "projects": []}},
            "identity_pack": {"payload": {"schema_version": "identity_pack.v1"}},
        }
    }

    out = asyncio.run(agent.create_ceo_advisor_agent(inp, ctx))
    tr = out.trace or {}

    assert isinstance(tr.get("kb_ids_used"), list)
    assert tr.get("kb_ids_used") == ["kb_a", "kb_b"]
