from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.job_templates_service import JobTemplatesService
from services.tools_catalog_service import ToolsCatalogService


def _write_json(p: Path, data: object) -> None:
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_tools_catalog_invalid_schema_fails(tmp_path: Path) -> None:
    bad_path = tmp_path / "tools.json"
    _write_json(bad_path, {"version": "1.0", "tools": []})

    svc = ToolsCatalogService()
    with pytest.raises(ValueError, match="non-empty 'tools' list"):
        svc.load_from_tools_json(str(bad_path), clear=True)


def test_job_templates_unknown_tool_action_fails(tmp_path: Path) -> None:
    tools_path = tmp_path / "tools.json"
    templates_path = tmp_path / "job_templates.json"

    _write_json(
        tools_path,
        {
            "version": "1.0",
            "tools": [
                {
                    "id": "read_only.query",
                    "description": "x",
                    "risk_level": "read_only",
                    "approval_required": True,
                    "runtime_action": "read_only.query",
                    "status": "mvp_executable",
                }
            ],
        },
    )

    _write_json(
        templates_path,
        {
            "version": "1.0",
            "job_templates": [
                {
                    "id": "JT-TEST-01",
                    "title": "t",
                    "role": "ops",
                    "steps": [
                        {
                            "tool_action": "does.not.exist",
                            "requires_approval": False,
                            "params_schema": {},
                        }
                    ],
                    "expected_outputs": [],
                }
            ],
        },
    )

    tools_svc = ToolsCatalogService()
    tools_svc.load_from_tools_json(str(tools_path), clear=True)

    templates_svc = JobTemplatesService()
    with pytest.raises(ValueError, match="unknown tool_action"):
        templates_svc.load_from_job_templates_json(
            tools_svc,
            str(templates_path),
            clear=True,
        )


def test_job_templates_invalid_schema_fails(tmp_path: Path) -> None:
    tools_path = tmp_path / "tools.json"
    templates_path = tmp_path / "job_templates.json"

    _write_json(
        tools_path,
        {
            "version": "1.0",
            "tools": [
                {
                    "id": "read_only.query",
                    "description": "x",
                    "risk_level": "read_only",
                    "approval_required": True,
                    "runtime_action": "read_only.query",
                    "status": "mvp_executable",
                }
            ],
        },
    )
    _write_json(templates_path, {"version": "1.0", "job_templates": []})

    tools_svc = ToolsCatalogService()
    tools_svc.load_from_tools_json(str(tools_path), clear=True)

    templates_svc = JobTemplatesService()
    with pytest.raises(ValueError, match="non-empty 'job_templates' list"):
        templates_svc.load_from_job_templates_json(
            tools_svc,
            str(templates_path),
            clear=True,
        )


@pytest.mark.anyio
async def test_planned_tool_execution_blocks(monkeypatch) -> None:
    import services.execution_orchestrator as eo
    from models.ai_command import AICommand

    # Avoid Notion service initialization in orchestrator.
    monkeypatch.setattr(eo, "get_notion_service", lambda: object())

    orch = eo.ExecutionOrchestrator()

    # Create + approve tool_call execution approval.
    approval = orch.approvals.create(
        command="tool_call",
        payload_summary={"action": "email.read"},
        scope="test",
        risk_level="standard",
        execution_id="exec_planned_1",
    )
    orch.approvals.approve(approval["approval_id"], approved_by="pytest")

    # email.read is PLANNED in tools.json; dept_growth is allowed to reference it via planned_tools_allowlist.
    cmd = AICommand(
        command="tool_call",
        intent="tool_call",
        params={"action": "email.read", "query": "hello"},
        initiator="system",
        execution_id="exec_planned_1",
        approval_id=approval["approval_id"],
        metadata={"agent_id": "dept_growth", "emit_handoff_log": False},
    )

    res = await orch.execute(cmd)
    assert isinstance(res, dict)
    assert res.get("execution_state") == "BLOCKED"

    inner = res.get("result")
    assert isinstance(inner, dict)
    assert inner.get("reason") == "tool_not_executable"
