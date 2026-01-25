from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_ceo_advisor_unknown_mode_must_not_fire_when_kb_ids_present(monkeypatch):
    """Regression: post-retrieval gate must NOT emit unknown-mode fallback when KB retrieval returned IDs.

    This reproduces the bug shape seen in /api/ceo/command traces where kb_ids_used_count > 0
    but the response still starts with "Trenutno nemam to znanje (nije u kuriranom KB-u / trenutnom snapshotu)".
    """

    # Use legacy assistants mode to avoid Responses-mode grounding guard.
    monkeypatch.setenv("OPENAI_API_MODE", "assistants")

    # Force unknown-mode policy active (i.e., do not allow general knowledge fallback).
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    # Force LLM configured so we exercise the LLM/synthesis path (with a dummy executor).
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: True)

    seen_ctx = {}

    class DummyExecutor:
        async def ceo_command(self, text, context):
            nonlocal seen_ctx
            seen_ctx = context

            gp = context.get("grounding_pack") if isinstance(context, dict) else None
            kb = gp.get("kb_retrieved") if isinstance(gp, dict) else None
            entries = kb.get("entries") if isinstance(kb, dict) else None

            assert (
                isinstance(entries, list) and entries
            ), "KB entries must be injected into synthesis context"
            first = entries[0]
            assert isinstance(first, dict)
            kid = first.get("id")
            content = first.get("content")
            assert isinstance(kid, str) and kid
            assert isinstance(content, str) and content

            return {
                "text": f"Odgovor je u KB-u: {content} [KB:{kid}]",
                "proposed_commands": [],
            }

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose: DummyExecutor(),
    )

    from models.agent_contract import AgentInput
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    kb_ids = [f"kb_test_{i:03d}" for i in range(1, 9)]
    kb_entries = [
        {
            "id": kb_ids[0],
            "title": "Test KB Entry",
            "content": "KB_SNIPPET_OK",
            "tags": ["test"],
            "priority": 1.0,
        }
    ]

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Šta kaže KB?",
                snapshot={},
                metadata={},
                preferred_agent_id="ceo_advisor",
            ),
            # Important: provide KB retrieval in ctx["kb"] (no grounding_pack), to
            # exercise back-compat extraction + injection.
            ctx={
                "kb": {
                    "used_entry_ids": kb_ids,
                    "entries": kb_entries,
                }
            },
        )
    )

    assert "Trenutno nemam to znanje" not in (out.text or "")
    assert "nije u kuriranom KB-u" not in (out.text or "")
    assert "KB_SNIPPET_OK" in (out.text or "")

    # Sanity: executor got the injected grounding_pack.
    assert isinstance(seen_ctx.get("grounding_pack"), dict)
