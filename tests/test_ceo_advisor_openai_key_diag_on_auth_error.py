from __future__ import annotations

import asyncio
import hashlib

import httpx
from openai import AuthenticationError


def _run(coro):
    return asyncio.run(coro)


def test_openai_key_diag_attached_on_auth_error(monkeypatch):
    """Regression: on 401 invalid_api_key, response must include key fingerprint diagnostics (no secrets)."""

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    key = "sk-proj-EXAMPLE_LOCAL_TEST_KEY_1234567890"
    monkeypatch.setenv("OPENAI_API_KEY", key)
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")

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
                message="test",
                snapshot={},
                metadata={},
                preferred_agent_id="ceo_advisor",
            ),
            ctx={
                "grounding_pack": {
                    "enabled": True,
                    "identity_pack": {"payload": {"available": True}},
                    "kb_retrieved": {"used_entry_ids": ["kb_001"], "entries": []},
                    "notion_snapshot": {},
                    "memory_snapshot": {"payload": {}},
                }
            },
        )
    )

    txt = out.text or ""
    assert "401" in txt
    assert "invalid_api_key" in txt
    assert "Trenutno nemam to znanje" not in txt

    diag = out.trace.get("llm_gate_diag")
    assert isinstance(diag, dict)

    openai_key = diag.get("openai_key")
    assert isinstance(openai_key, dict)

    # Must not leak the raw key
    assert key not in str(openai_key)

    assert openai_key.get("present") is True
    assert openai_key.get("len") == len(key)
    assert openai_key.get("prefix") == key[:7]

    fp = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    assert openai_key.get("fingerprint") == fp
    assert openai_key.get("mode") == "responses"
