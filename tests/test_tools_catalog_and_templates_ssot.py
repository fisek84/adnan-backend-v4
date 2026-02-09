from __future__ import annotations

import json
from pathlib import Path

import pytest


def _load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_tools_catalog_exists_and_marks_mvp_executable() -> None:
    p = Path("config/tools.json")
    assert p.exists(), "missing config/tools.json"

    data = _load_json(p)
    tools = data.get("tools")
    assert isinstance(tools, list) and tools

    by_id = {t.get("id"): t for t in tools if isinstance(t, dict)}

    # MVP tools must exist and be executable
    for tool_id in [
        "read_only.query",
        "analysis.run",
        "draft.outreach",
        "draft.spec",
        "draft.issue",
    ]:
        t = by_id.get(tool_id)
        assert isinstance(t, dict), f"missing tool id={tool_id}"
        assert t.get("status") == "mvp_executable"
        assert t.get("runtime_action") == tool_id

    # Planned tools must be present but not executable
    planned = [
        "email.read",
        "email.draft",
        "email.send",
        "sheets.read",
        "sheets.write",
        "sheets.export",
        "leads.search",
        "leads.create",
        "leads.sequence_draft",
        "tickets.create",
        "tickets.update",
        "docs.write",
        "calendar.read",
        "calendar.propose",
        "finance.report_generate",
        "finance.categorize",
        "import_bank",
    ]
    for tool_id in planned:
        t = by_id.get(tool_id)
        assert isinstance(t, dict), f"missing planned tool id={tool_id}"
        assert t.get("status") == "planned"
        assert t.get("runtime_action") in (None, "")


def test_agents_allowlist_matches_mvp_catalog() -> None:
    agents_path = Path("config/agents.json")
    assert agents_path.exists()

    data = _load_json(agents_path)
    agents = data.get("agents")
    assert isinstance(agents, list) and agents

    by_id = {a.get("id"): a for a in agents if isinstance(a, dict)}

    def _allow(agent_id: str) -> list[str]:
        a = by_id[agent_id]
        md = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
        al = md.get("tool_allowlist")
        assert isinstance(al, list)
        return [str(x) for x in al]

    assert "read_only.query" in _allow("dept_ops")
    al_fin = _allow("dept_finance")
    assert "analysis.run" in al_fin
    assert "read_only.query" in al_fin

    al_prod = _allow("dept_product")
    assert "draft.spec" in al_prod
    assert "draft.issue" in al_prod

    al_growth = _allow("dept_growth")
    assert "draft.outreach" in al_growth


def test_job_templates_exist_and_reference_mvp_tools() -> None:
    p = Path("config/job_templates.json")
    assert p.exists(), "missing config/job_templates.json"

    data = _load_json(p)
    templates = data.get("job_templates")
    assert isinstance(templates, list) and templates

    for t in templates:
        assert isinstance(t, dict)
        assert isinstance(t.get("id"), str) and t["id"].strip()
        assert isinstance(t.get("role"), str) and t["role"].strip()
        steps = t.get("steps")
        assert isinstance(steps, list) and steps
        for s in steps:
            assert isinstance(s, dict)
            assert isinstance(s.get("tool_action"), str) and s["tool_action"].strip()


@pytest.mark.anyio
async def test_job_template_step_requires_allowlist_or_blocked(monkeypatch) -> None:
    import services.execution_orchestrator as eo
    from models.ai_command import AICommand

    # Avoid Notion service initialization in orchestrator.
    monkeypatch.setattr(eo, "get_notion_service", lambda: object())
    orch = eo.ExecutionOrchestrator()

    # Create + approve tool_call execution approval.
    approval = orch.approvals.create(
        command="tool_call",
        payload_summary={"action": "analysis.run"},
        scope="test",
        risk_level="standard",
        execution_id="exec_template_1",
    )
    orch.approvals.approve(approval["approval_id"], approved_by="pytest")

    # dept_ops should NOT be allowed to run analysis.run (per SSOT mapping).
    cmd = AICommand(
        command="tool_call",
        intent="tool_call",
        params={"action": "analysis.run", "expression": "1 + 2"},
        initiator="system",
        execution_id="exec_template_1",
        approval_id=approval["approval_id"],
        metadata={"agent_id": "dept_ops", "emit_handoff_log": False},
    )

    res = await orch.execute(cmd)
    assert isinstance(res, dict)
    assert res.get("execution_state") == "BLOCKED"

    inner = res.get("result")
    assert isinstance(inner, dict)
    assert inner.get("reason") == "action_not_allowed"


@pytest.mark.anyio
async def test_tool_call_requires_approval_even_if_allowlisted(monkeypatch) -> None:
    import services.execution_orchestrator as eo
    from models.ai_command import AICommand

    monkeypatch.setattr(eo, "get_notion_service", lambda: object())
    orch = eo.ExecutionOrchestrator()

    cmd = AICommand(
        command="tool_call",
        intent="tool_call",
        params={"action": "analysis.run", "expression": "1 + 2"},
        initiator="system",
        execution_id="exec_noappr_1",
        approval_id="",
        metadata={"agent_id": "dept_finance", "emit_handoff_log": False},
    )

    res = await orch.execute(cmd)
    assert isinstance(res, dict)
    assert res.get("execution_state") == "BLOCKED"
