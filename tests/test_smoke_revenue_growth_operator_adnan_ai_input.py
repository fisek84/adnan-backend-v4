from __future__ import annotations

import json
import os
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _offline_contract(*, objective: str) -> Dict[str, Any]:
    return {
        "agent": "revenue_growth_operator",
        "task_id": None,
        "objective": objective,
        "context_ref": {
            "lead_id": None,
            "account_id": None,
            "meeting_id": None,
            "campaign_id": None,
        },
        "work_done": [],
        "next_steps": [],
        "recommendations_to_ceo": [],
        "requests_from_ceo": [],
        "notion_ops_proposal": [],
    }


def _install_offline_stubs(*, mode: str, monkeypatch) -> None:
    import services.revenue_growth_operator_agent as rgo

    if mode == "assistants":
        expected = "asst_test_revenue"
        monkeypatch.setenv("REVENUE_GROWTH_OPERATOR_ASSISTANT_ID", expected)

        class _DummyExecutor:
            async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
                assert task.get("assistant_id") == expected
                assert task.get("allow_tools") is False
                return _offline_contract(objective=str(task.get("input") or ""))

        monkeypatch.setattr(rgo, "get_executor", lambda purpose: _DummyExecutor())

    elif mode == "responses":
        monkeypatch.setenv("REVENUE_GROWTH_OPERATOR_MODEL", "gpt-test-model")

        class _DummyResponsesExecutor:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
                assert task.get("allow_tools") is False
                return _offline_contract(objective=str(task.get("input") or ""))

        monkeypatch.setattr(rgo, "OpenAIResponsesExecutor", _DummyResponsesExecutor)

    else:
        raise ValueError(mode)


def _assert_response_contract(body: Dict[str, Any]) -> None:
    assert body.get("read_only") is True

    pcs = body.get("proposed_commands")
    assert isinstance(pcs, list)
    assert pcs == []

    raw = body.get("text")
    assert isinstance(raw, str) and raw.strip()

    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    assert parsed.get("agent") == "revenue_growth_operator"

    lowered = raw.lower()
    forbidden = ("proposedcommand", "notion_write", "dispatch", "tool_call")
    assert not any(f in lowered for f in forbidden)


@pytest.mark.parametrize("mode", ["assistants", "responses"])
def test_smoke_revenue_growth_operator_via_existing_adnan_ai_input_endpoint(mode, monkeypatch, capsys):
    # Keep this smoke test fully read-only and deterministic.
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.setenv("OPENAI_API_MODE", mode)

    # Avoid real OpenAI calls while still exercising the existing HTTP endpoint.
    _install_offline_stubs(mode=mode, monkeypatch=monkeypatch)

    app = _load_app()
    client = TestClient(app)

    # 1) Explicit selection
    r1 = client.post(
        "/api/adnan-ai/input",
        json={
            # Must pass COOConversationService gate (ready_for_translation) before
            # the legacy wrapper forwards to AgentRouterService.
            "text": "Pregledaj stanje sistema. Draft sales outreach followup email.",
            "context": {},
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
            "preferred_agent_id": "revenue_growth_operator",
        },
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    print("raw AgentOutput.text (explicit):")
    print(b1.get("text"))
    _assert_response_contract(b1)

    # 2) Keyword routing
    r2 = client.post(
        "/api/adnan-ai/input",
        json={
            # Include SYSTEM_QUERY phrase to pass the COO gate, while still
            # containing growth keywords for deterministic keyword routing.
            "text": "Pregledaj stanje sistema. sales outreach followup for pipeline",
            "context": {},
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
        },
    )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    print("raw AgentOutput.text (keywords):")
    print(b2.get("text"))
    _assert_response_contract(b2)

    # Ensure prints are actually produced in -s runs.
    out = capsys.readouterr().out
    assert "raw AgentOutput.text" in out
