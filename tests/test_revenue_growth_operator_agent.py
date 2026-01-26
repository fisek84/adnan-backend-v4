from __future__ import annotations

import json
import os
from typing import Any, Dict

import pytest

from models.agent_contract import AgentInput
from services.agent_registry_service import AgentRegistryService
from services.agent_router_service import AgentRouterService


def _load_registry() -> AgentRegistryService:
    reg = AgentRegistryService()
    reg.load_from_agents_json("config/agents.json", clear=True)
    return reg


def test_registry_loads_revenue_growth_operator_from_ssot():
    reg = _load_registry()
    entry = reg.get_agent("revenue_growth_operator")
    assert entry is not None
    assert entry.enabled is True
    assert entry.name == "Revenue & Growth Operator"
    assert entry.priority < reg.get_agent("ceo_advisor").priority  # type: ignore[union-attr]

    md = entry.metadata or {}
    assert md.get("assistant_id") == "ENV:REVENUE_GROWTH_OPERATOR_ASSISTANT_ID"


@pytest.mark.anyio
async def test_router_routes_by_keywords_and_executes_json_contract(monkeypatch):
    reg = _load_registry()
    router = AgentRouterService(reg)

    # Ensure assistant env binding is present.
    monkeypatch.setenv("REVENUE_GROWTH_OPERATOR_ASSISTANT_ID", "asst_test_revenue")
    monkeypatch.setenv("OPENAI_API_MODE", "assistants")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-local")

    captured: Dict[str, Any] = {}

    class _DummyExecutor:
        async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
            # ENV binding must be resolved before calling the executor.
            assert task.get("assistant_id") == "asst_test_revenue"
            assert task.get("allow_tools") is False
            assert task.get("response_format") == {"type": "json_object"}
            captured["task"] = task

            return {
                "agent": "revenue_growth_operator",
                "task_id": None,
                "objective": "Draft outreach",
                "context_ref": {
                    "lead_id": None,
                    "account_id": None,
                    "meeting_id": None,
                    "campaign_id": None,
                },
                "work_done": [
                    {
                        "type": "email_draft",
                        "title": "Intro email",
                        "content": "Hello ...",
                        "meta": {},
                    }
                ],
                "next_steps": [{"action": "Send email", "owner": "me", "due": None}],
                "recommendations_to_ceo": [],
                "requests_from_ceo": [],
                "notion_ops_proposal": [],
            }

    # Patch the executor factory used by the agent module.
    import services.revenue_growth_operator_agent as rgo

    monkeypatch.setattr(rgo, "get_executor", lambda purpose: _DummyExecutor())

    out = await router.route(
        AgentInput(
            message="Need sales outreach for pipeline followup",
            metadata={"read_only": True, "require_approval": True},
        )
    )

    assert out.agent_id == "revenue_growth_operator"
    payload = json.loads(out.text)
    assert payload["agent"] == "revenue_growth_operator"
    assert isinstance(payload.get("work_done"), list)


@pytest.mark.anyio
async def test_router_routes_by_preferred_agent_id(monkeypatch):
    reg = _load_registry()
    router = AgentRouterService(reg)

    monkeypatch.setenv("REVENUE_GROWTH_OPERATOR_ASSISTANT_ID", "asst_test_revenue")
    monkeypatch.setenv("OPENAI_API_MODE", "assistants")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-local")

    class _DummyExecutor:
        async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "agent": "revenue_growth_operator",
                "task_id": None,
                "objective": "Ok",
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

    import services.revenue_growth_operator_agent as rgo

    monkeypatch.setattr(rgo, "get_executor", lambda purpose: _DummyExecutor())

    out = await router.route(
        AgentInput(
            message="hello",
            preferred_agent_id="revenue_growth_operator",
            metadata={"read_only": True, "require_approval": True},
        )
    )

    assert out.agent_id == "revenue_growth_operator"
    payload = json.loads(out.text)
    assert payload["agent"] == "revenue_growth_operator"


def test_agent_has_no_notion_or_write_imports():
    # Defense-in-depth: this agent must not import Notion services.
    import ast
    from pathlib import Path

    p = Path("services/revenue_growth_operator_agent.py")
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)

    forbidden_import_substrings = (
        "services.notion",
        "integrations.notion",
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                assert not any(s in name for s in forbidden_import_substrings), name
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not any(s in mod for s in forbidden_import_substrings), mod
