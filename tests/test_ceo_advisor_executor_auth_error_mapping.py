from __future__ import annotations

import asyncio

import httpx
from openai import AuthenticationError


def _run(coro):
    return asyncio.run(coro)


def test_ceo_advisor_executor_auth_error_invalid_api_key_is_explicit(monkeypatch):
    """Regression: 401 invalid_api_key must be reported explicitly (not as KB/snapshot missing)."""

    monkeypatch.setenv("OPENAI_API_MODE", "assistants")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")

    # Force LLM configured so we go through executor path.
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: True)

    class DummyExecutor:
        async def ceo_command(self, text, context):
            resp = httpx.Response(
                status_code=401,
                request=httpx.Request(
                    "POST", "https://api.openai.com/v1/chat/completions"
                ),
                json={
                    "error": {"code": "invalid_api_key", "message": "Invalid API key"}
                },
            )
            raise AuthenticationError(
                "401 Unauthorized",
                response=resp,
                body={"error": {"code": "invalid_api_key"}},
            )

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose: DummyExecutor(),
    )

    from models.agent_contract import AgentInput
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Koji je status?",
                snapshot={},
                metadata={},
                preferred_agent_id="ceo_advisor",
            ),
            ctx={
                # Provide grounding to match the reported runtime scenario.
                "grounding_pack": {
                    "enabled": True,
                    "identity_pack": {"payload": {"available": True}},
                    "kb_retrieved": {
                        "used_entry_ids": ["kb_001"],
                        "entries": [{"id": "kb_001", "title": "t", "content": "c"}],
                    },
                    "notion_snapshot": {},
                    "memory_snapshot": {"payload": {}},
                }
            },
        )
    )

    assert out.trace.get("exit_reason") == "offline.executor_error"

    txt = out.text or ""
    assert "invalid_api_key" in txt
    assert "Trenutno nemam to znanje" not in txt
    assert "nije u kuriranom KB-u" not in txt

    diag = out.trace.get("llm_gate_diag")
    assert isinstance(diag, dict)
    assert diag.get("status") == 401
    assert diag.get("code") == "invalid_api_key"
    assert diag.get("kind") == "auth"
