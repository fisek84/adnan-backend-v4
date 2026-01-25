from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_ceo_advisor_cites_kb_even_when_snapshot_budget_exceeded(monkeypatch):
    # Force LLM path (but with a dummy executor).
    monkeypatch.setenv("OPENAI_API_MODE", "assistants")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: True)

    class DummyExecutor:
        async def ceo_command(self, text, context):
            gp = context.get("grounding_pack") if isinstance(context, dict) else None
            assert isinstance(gp, dict)

            kb = (
                gp.get("kb_retrieved")
                if isinstance(gp.get("kb_retrieved"), dict)
                else {}
            )
            entries = kb.get("entries") if isinstance(kb.get("entries"), list) else []
            assert (
                entries
            ), "KB entries must be present even when snapshot is budget-exceeded"

            e0 = entries[0]
            assert isinstance(e0, dict)
            kid = e0.get("id")
            assert isinstance(kid, str) and kid

            return {"text": f"Odgovor je u KB-u. [KB:{kid}]", "proposed_commands": []}

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose: DummyExecutor(),
    )

    from models.agent_contract import AgentInput
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    gp = {
        "enabled": True,
        "kb_retrieved": {
            "entries": [
                {
                    "id": "kb_test_001",
                    "title": "KB",
                    "content": "KB_CONTENT",
                    "tags": [],
                    "priority": 1.0,
                }
            ],
            "used_entry_ids": ["kb_test_001"],
            "meta": {"total_entries": 1, "hit_count": 1, "mode": "notion"},
        },
        "notion_snapshot": {
            "schema_version": "v1",
            "status": "stale",
            "payload": {"goals": [], "tasks": [], "projects": []},
            "meta": {"budget": {"exceeded": True, "exceeded_kind": "max_latency_ms"}},
        },
    }

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(message="Šta kaže KB?", snapshot={}, metadata={}),
            ctx={"grounding_pack": gp},
        )
    )

    assert "Trenutno nemam to znanje" not in (out.text or "")
    assert "[KB:kb_test_001]" in (out.text or "")
