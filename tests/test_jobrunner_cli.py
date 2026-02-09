from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from scripts.jobrunner_cli_lib import map_step_params, resume_job, start_job


class DummyResp:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


def _write_json(p: Path, obj: Any) -> str:
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_map_step_params_missing_required_raises() -> None:
    with pytest.raises(KeyError):
        map_step_params(
            params_schema={"a": {"type": "string"}, "b": {}}, inputs={"a": 1}
        )


def test_start_posts_execute_raw_and_writes_approvals(tmp_path: Path) -> None:
    tools_path = _write_json(
        tmp_path / "tools.json",
        {
            "version": "1.0",
            "tools": [{"id": "analysis.run", "status": "mvp_executable"}],
        },
    )

    templates_path = _write_json(
        tmp_path / "job_templates.json",
        {
            "version": "1.0",
            "job_templates": [
                {
                    "id": "JT-X",
                    "role": "finance",
                    "steps": [
                        {
                            "tool_action": "analysis.run",
                            "params_schema": {"expression": {"type": "string"}},
                        },
                        {
                            "tool_action": "analysis.run",
                            "params_schema": {"expression": {"type": "string"}},
                        },
                    ],
                }
            ],
        },
    )

    agents_path = _write_json(
        tmp_path / "agents.json",
        {
            "version": "1.0",
            "agents": [
                {
                    "id": "dept_finance",
                    "name": "Dept Finance",
                    "enabled": True,
                    "priority": 10,
                    "entrypoint": "services.department_agents:dept_finance_agent",
                    "role": "finance",
                }
            ],
        },
    )

    calls: List[Tuple[str, Dict[str, Any]]] = []

    def fake_post(url: str, json: Dict[str, Any], timeout: float = 0) -> DummyResp:  # type: ignore[override]
        calls.append((url, json))
        idx = len(calls)
        return DummyResp(
            {
                "execution_state": "BLOCKED",
                "approval_id": f"a{idx}",
                "execution_id": f"e{idx}",
            }
        )

    out = start_job(
        base_url="http://127.0.0.1:8000",
        template_id="JT-X",
        job_id="job123",
        initiator="smoke",
        inputs={"expression": "1+1"},
        job_templates_path=templates_path,
        tools_path=tools_path,
        agents_json_path=agents_path,
        output_dir=str(tmp_path),
        post=fake_post,
    )

    assert len(calls) == 2
    assert calls[0][0].endswith("/api/execute/raw")
    assert calls[0][1]["command"] == "tool_call"
    assert calls[0][1]["params"]["action"] == "analysis.run"
    assert calls[0][1]["params"]["expression"] == "1+1"
    assert calls[0][1]["metadata"]["job_id"] == "job123"
    assert calls[0][1]["metadata"]["template_id"] == "JT-X"
    assert calls[0][1]["metadata"]["step_id"] == "JT-X:step_1"

    approvals_file = Path(out.approvals_file)
    assert approvals_file.exists()
    approvals = json.loads(approvals_file.read_text(encoding="utf-8"))
    assert approvals == {"JT-X:step_1": "a1", "JT-X:step_2": "a2"}


def test_resume_posts_approve_and_writes_results(tmp_path: Path) -> None:
    calls: List[Tuple[str, Dict[str, Any]]] = []

    def fake_post(url: str, json: Dict[str, Any], timeout: float = 0) -> DummyResp:  # type: ignore[override]
        calls.append((url, json))
        return DummyResp(
            {
                "execution_state": "COMPLETED",
                "execution_id": "exec1",
                "result": {"ok": True},
            }
        )

    res = resume_job(
        base_url="http://127.0.0.1:8000",
        job_id="job123",
        initiator="smoke",
        approvals_by_step={"JT-X:step_1": "a1", "JT-X:step_2": "a2"},
        output_dir=str(tmp_path),
        post=fake_post,
    )

    assert len(calls) == 2
    assert calls[0][0].endswith("/api/ai-ops/approval/approve")
    assert calls[0][1]["approval_id"] == "a1"
    assert calls[0][1]["approved_by"] == "smoke"

    results_file = Path(res.results_file)
    assert results_file.exists()
    results = json.loads(results_file.read_text(encoding="utf-8"))
    assert isinstance(results, list)
    assert results[0]["execution_state"] == "COMPLETED"


def test_resume_planned_tool_blocks(tmp_path: Path) -> None:
    def fake_post(url: str, json: Dict[str, Any], timeout: float = 0) -> DummyResp:  # type: ignore[override]
        return DummyResp(
            {
                "execution_state": "BLOCKED",
                "execution_id": "exec_planned",
                "result": {
                    "execution_state": "BLOCKED",
                    "reason": "tool_not_executable",
                },
            }
        )

    res = resume_job(
        base_url="http://127.0.0.1:8000",
        job_id="job_planned",
        initiator="smoke",
        approvals_by_step={"JT-PLANNED:step_1": "a-planned"},
        output_dir=str(tmp_path),
        post=fake_post,
    )

    assert res.step_results[0]["execution_state"] == "BLOCKED"
    assert res.step_results[0]["result"]["reason"] == "tool_not_executable"
