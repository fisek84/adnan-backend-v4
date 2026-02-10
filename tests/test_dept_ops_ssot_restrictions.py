from __future__ import annotations


def test_dept_ops_tool_allowlist_excludes_analysis_run() -> None:
    from services.agent_registry_service import AgentRegistryService

    reg = AgentRegistryService()
    reg.load_from_agents_json("config/agents.json", clear=True)

    entry = reg.get_agent("dept_ops")
    assert entry is not None
    md = entry.metadata
    allow = md.get("tool_allowlist") if isinstance(md, dict) else None
    assert allow == ["read_only.query"], "dept_ops must be proposal-only + read_only.query only"
    assert "analysis.run" not in set(allow or [])
