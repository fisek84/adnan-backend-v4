from __future__ import annotations

import ast
from pathlib import Path

import pytest

from models.agent_contract import AgentInput
from services.agent_registry_service import AgentRegistryService
from services.agent_router_service import AgentRouterService


def _load_registry_from_agents_json() -> AgentRegistryService:
    reg = AgentRegistryService()
    reg.load_from_agents_json("config/agents.json", clear=True)
    return reg


def _set_agent_status(
    reg: AgentRegistryService,
    *,
    agent_id: str,
    enabled: bool,
) -> None:
    entry = reg.get_agent(agent_id)
    assert entry is not None, f"missing agent in registry: {agent_id}"

    status = "active" if enabled else "disabled"
    md = dict(entry.metadata or {})
    md["entrypoint"] = entry.entrypoint
    md["priority"] = entry.priority
    md["keywords"] = list(entry.keywords or [])

    reg.register_agent(
        agent_name=agent_id,
        agent_id=agent_id,
        capabilities=list(entry.capabilities or []),
        version=entry.version,
        status=status,
        metadata=md,
    )


@pytest.mark.anyio
async def test_preferred_agent_id_does_not_select_disabled_dept_agent():
    reg = _load_registry_from_agents_json()
    router = AgentRouterService(reg)

    # Dept agents are prod-default disabled.
    entry = reg.get_agent("dept_growth")
    assert entry is not None
    assert entry.enabled is False

    agent_input = AgentInput(
        message="hello",
        preferred_agent_id="dept_growth",
        metadata={"read_only": True, "require_approval": True},
    )

    out = await router.route(agent_input)

    assert out.agent_id != "dept_growth"
    # With score=0 prompts, highest priority enabled agent should win (ceo_advisor).
    assert out.agent_id == "ceo_advisor"


@pytest.mark.anyio
async def test_preferred_agent_id_selects_enabled_dept_agent_deterministically():
    reg = _load_registry_from_agents_json()
    _set_agent_status(reg, agent_id="dept_growth", enabled=True)

    router = AgentRouterService(reg)

    agent_input = AgentInput(
        message="hello",
        preferred_agent_id="dept_growth",
        metadata={"read_only": True, "require_approval": True},
    )

    out = await router.route(agent_input)

    assert out.agent_id == "dept_growth"
    assert isinstance(out.trace, dict)
    assert out.trace.get("selected_by") == "preferred_agent_id"
    assert out.trace.get("selected_agent_id") == "dept_growth"
    assert (
        out.trace.get("selected_entrypoint")
        == "services.department_agents:dept_growth_agent"
    )


@pytest.mark.anyio
async def test_enabled_dept_agents_with_empty_keywords_do_not_steal_normal_prompts():
    reg = _load_registry_from_agents_json()

    for agent_id in ("dept_growth", "dept_product", "dept_finance", "dept_ops"):
        _set_agent_status(reg, agent_id=agent_id, enabled=True)

    router = AgentRouterService(reg)

    agent_input = AgentInput(
        message="hello",
        metadata={"read_only": True, "require_approval": True},
    )

    out = await router.route(agent_input)
    assert out.agent_id == "ceo_advisor"


def test_department_agents_module_has_no_notion_or_write_gateway_imports_or_symbols():
    p = Path("services/department_agents.py")
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # NOTE: This test intentionally does NOT grep for substrings like "notion" in
    # string literals. It only asserts on real code-level dependencies (imports and
    # symbol references), to avoid brittle failures when text templates mention Notion.

    forbidden_import_substrings = (
        "services.notion",
        "write_gateway",
    )

    forbidden_names = {
        # Canonical writer-facing services / gateways
        "NotionService",
        "WriteGateway",
        # Common writer agent names (defense-in-depth)
        "NotionOpsAgent",
    }

    # Imports: must not import notion writer modules or write gateway modules.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                assert not any(s in name for s in forbidden_import_substrings), name
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not any(s in mod for s in forbidden_import_substrings), mod

    # Symbols: must not reference NotionService/WriteGateway names.
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden_names
        if isinstance(node, ast.Attribute):
            attr = node.attr
            assert attr not in forbidden_names
