from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from services.agent_registry_service import AgentRegistryService


JsonDict = Dict[str, Any]


def _safe_str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def load_json_file(path: str) -> Any:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def write_json_file(path: str, data: Any) -> None:
    p = Path(path)
    p.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def load_job_template(*, template_id: str, job_templates_path: str) -> JsonDict:
    tid = _safe_str(template_id)
    data = load_json_file(job_templates_path)
    if not isinstance(data, dict):
        raise ValueError("job_templates.json must be an object")

    items = data.get("job_templates")
    if not isinstance(items, list):
        raise ValueError("job_templates.json missing job_templates list")

    for t in items:
        if isinstance(t, dict) and _safe_str(t.get("id")) == tid:
            return t

    raise KeyError(f"template_not_found:{tid}")


def resolve_dept_agent_id_for_role(*, role: str, agents_json_path: str) -> str:
    role_norm = _safe_str(role).lower()
    if not role_norm:
        raise ValueError("role is required")

    reg = AgentRegistryService()
    reg.load_from_agents_json(agents_json_path, clear=True)

    for entry in reg.list_agents(enabled_only=True):
        if not isinstance(getattr(entry, "id", None), str):
            continue
        if not entry.id.startswith("dept_"):
            continue
        md = (
            entry.metadata if isinstance(getattr(entry, "metadata", None), dict) else {}
        )
        if _safe_str(md.get("role")).lower() == role_norm:
            return entry.id

    raise KeyError(f"no_dept_agent_for_role:{role_norm}")


def map_step_params(*, params_schema: Any, inputs: Any) -> JsonDict:
    if not isinstance(params_schema, dict):
        params_schema = {}
    if not isinstance(inputs, dict):
        inputs = {}

    missing: List[str] = []
    mapped: JsonDict = {}

    for k in sorted(params_schema.keys()):
        if not isinstance(k, str) or not k.strip():
            continue
        if k not in inputs:
            missing.append(k)
            continue
        mapped[k] = inputs.get(k)

    if missing:
        raise KeyError(f"missing_required_inputs:{','.join(missing)}")

    return mapped


def build_execute_raw_payload(
    *,
    tool_action: str,
    mapped_params: JsonDict,
    initiator: str,
    metadata: JsonDict,
) -> JsonDict:
    return {
        "command": "tool_call",
        "intent": "tool_call",
        "params": {"action": _safe_str(tool_action), **(mapped_params or {})},
        "initiator": _safe_str(initiator) or "system",
        "metadata": metadata or {},
    }


@dataclass(frozen=True)
class StartResult:
    job_id: str
    template_id: str
    agent_id: str
    approvals_by_step: Dict[str, str]
    step_results: List[JsonDict]
    approvals_file: str


@dataclass(frozen=True)
class ResumeResult:
    job_id: str
    results_file: str
    step_results: List[JsonDict]


def start_job(
    *,
    base_url: str,
    template_id: str,
    job_id: str,
    initiator: str,
    inputs: JsonDict,
    job_templates_path: str,
    tools_path: str,  # loaded for spec compliance; not required for mapping
    agents_json_path: str,
    output_dir: str,
    post: Callable[..., Any] = requests.post,
    timeout_seconds: float = 30.0,
) -> StartResult:
    _ = load_json_file(tools_path)  # validate file exists / parseable

    tmpl = load_job_template(
        template_id=template_id, job_templates_path=job_templates_path
    )
    role = _safe_str(tmpl.get("role"))
    agent_id = resolve_dept_agent_id_for_role(
        role=role, agents_json_path=agents_json_path
    )

    steps = tmpl.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("template has no steps")

    tid = _safe_str(template_id)
    jid = _safe_str(job_id)
    if not jid:
        raise ValueError("job_id is required")

    approvals_by_step: Dict[str, str] = {}
    step_results: List[JsonDict] = []

    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"invalid_step:{idx}")

        step_id = f"{tid}:step_{idx + 1}" if tid else f"step_{idx + 1}"
        tool_action = _safe_str(step.get("tool_action"))
        if not tool_action:
            raise ValueError(f"missing_tool_action:{step_id}")

        params_schema = step.get("params_schema")
        mapped = map_step_params(params_schema=params_schema, inputs=inputs)

        metadata = {
            "agent_id": agent_id,
            "job_id": jid,
            "template_id": tid,
            "step_id": step_id,
            "job_runner": True,
        }

        payload = build_execute_raw_payload(
            tool_action=tool_action,
            mapped_params=mapped,
            initiator=initiator,
            metadata=metadata,
        )

        url = _safe_str(base_url).rstrip("/") + "/api/execute/raw"
        resp = post(url, json=payload, timeout=timeout_seconds)
        resp_json = resp.json() if hasattr(resp, "json") else {}

        approval_id = _safe_str(resp_json.get("approval_id"))
        execution_id = _safe_str(resp_json.get("execution_id"))
        execution_state = _safe_str(resp_json.get("execution_state"))

        if not approval_id:
            raise RuntimeError(f"missing_approval_id_for_step:{step_id}")

        approvals_by_step[step_id] = approval_id
        step_results.append(
            {
                "step_id": step_id,
                "tool_action": tool_action,
                "approval_id": approval_id,
                "execution_id": execution_id,
                "execution_state": execution_state,
                "response": resp_json,
            }
        )

    out_path = str(Path(output_dir) / f"_job_{jid}_pending_approvals.json")
    write_json_file(out_path, approvals_by_step)

    return StartResult(
        job_id=jid,
        template_id=tid,
        agent_id=agent_id,
        approvals_by_step=approvals_by_step,
        step_results=step_results,
        approvals_file=out_path,
    )


def resume_job(
    *,
    base_url: str,
    job_id: str,
    initiator: str,
    approvals_by_step: Dict[str, str],
    output_dir: str,
    post: Callable[..., Any] = requests.post,
    timeout_seconds: float = 30.0,
    on_step_result: Optional[Callable[[JsonDict], None]] = None,
) -> ResumeResult:
    jid = _safe_str(job_id)
    if not jid:
        raise ValueError("job_id is required")
    if not isinstance(approvals_by_step, dict) or not approvals_by_step:
        raise ValueError("approvals_by_step must be a non-empty mapping")

    url = _safe_str(base_url).rstrip("/") + "/api/ai-ops/approval/approve"

    step_results: List[JsonDict] = []
    for step_id in sorted(approvals_by_step.keys()):
        approval_id = _safe_str(approvals_by_step.get(step_id))
        if not approval_id:
            raise ValueError(f"missing_approval_id_for_step:{step_id}")

        body = {
            "approval_id": approval_id,
            "approved_by": _safe_str(initiator) or "unknown",
            "note": f"jobrunner_cli resume job_id={jid} step_id={step_id}",
        }

        resp = post(url, json=body, timeout=timeout_seconds)
        resp_json = resp.json() if hasattr(resp, "json") else {}
        rec = {
            "step_id": step_id,
            "approval_id": approval_id,
            "execution_id": resp_json.get("execution_id"),
            "execution_state": resp_json.get("execution_state"),
            "result": resp_json.get("result"),
            "response": resp_json,
        }
        step_results.append(rec)

        if on_step_result is not None:
            try:
                on_step_result(dict(rec))
            except Exception:
                pass

    out_path = str(Path(output_dir) / f"_job_{jid}_results.json")
    write_json_file(out_path, step_results)

    return ResumeResult(job_id=jid, results_file=out_path, step_results=step_results)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobrunner_cli")
    p.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Gateway base URL (default: http://127.0.0.1:8000)",
    )

    sub = p.add_subparsers(dest="subcmd", required=True)

    p_start = sub.add_parser("start", help="Start a job template (create approvals)")
    p_start.add_argument("--template", required=True)
    p_start.add_argument("--job-id", required=True)
    p_start.add_argument("--initiator", required=True)
    p_start.add_argument("--inputs-json", required=False)
    p_start.add_argument("--job-templates", default="config/job_templates.json")
    p_start.add_argument("--tools", default="config/tools.json")
    p_start.add_argument("--agents", default="config/agents.json")
    p_start.add_argument("--output-dir", default=".")

    p_resume = sub.add_parser("resume", help="Approve and execute pending steps")
    p_resume.add_argument("--job-id", required=True)
    p_resume.add_argument("--initiator", required=True)
    p_resume.add_argument("--approvals-json", required=True)
    p_resume.add_argument("--output-dir", default=".")

    return p


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    return build_arg_parser().parse_args(argv)
