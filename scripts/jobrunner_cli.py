from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from scripts.jobrunner_cli_lib import parse_args, resume_job, start_job


def _read_inputs_json(path: str | None) -> Dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("inputs-json must contain a JSON object")
    return data


def _read_approvals_json(path: str) -> Dict[str, str]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(
            "approvals-json must contain a JSON object mapping step_id->approval_id"
        )

    out: Dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip():
            out[k.strip()] = v.strip()
    if not out:
        raise ValueError("approvals-json is empty")
    return out


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv)

    if ns.subcmd == "start":
        inputs = _read_inputs_json(ns.inputs_json)
        res = start_job(
            base_url=ns.base_url,
            template_id=ns.template,
            job_id=ns.job_id,
            initiator=ns.initiator,
            inputs=inputs,
            job_templates_path=ns.job_templates,
            tools_path=ns.tools,
            agents_json_path=ns.agents,
            output_dir=ns.output_dir,
        )

        print(
            json.dumps(
                {
                    "ok": True,
                    "job_id": res.job_id,
                    "template_id": res.template_id,
                    "agent_id": res.agent_id,
                    "approvals_file": res.approvals_file,
                    "approvals_by_step": res.approvals_by_step,
                    "steps": len(res.step_results),
                    "pending_approvals": len(res.approvals_by_step),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        print("")
        print(f"Pending approvals written: {res.approvals_file}")
        next_cmd = (
            "Next: python scripts/jobrunner_cli.py resume "
            f"--job-id {res.job_id} "
            f"--initiator {ns.initiator} "
            f"--approvals-json {res.approvals_file}"
        )
        print(next_cmd)
        return 0

    if ns.subcmd == "resume":
        approvals_by_step = _read_approvals_json(ns.approvals_json)

        def _print_step(rec: Dict[str, Any]) -> None:
            step_id = rec.get("step_id")
            approval_id = rec.get("approval_id")
            state = rec.get("execution_state")
            result = rec.get("result")
            reason = None
            if isinstance(result, dict):
                reason = (
                    result.get("reason")
                    or result.get("message")
                    or result.get("detail")
                )
            tail = (
                f" reason={reason}"
                if isinstance(reason, str) and reason.strip()
                else ""
            )
            print(
                f"approve step_id={step_id} approval_id={approval_id} state={state}{tail}"
            )

        res = resume_job(
            base_url=ns.base_url,
            job_id=ns.job_id,
            initiator=ns.initiator,
            approvals_by_step=approvals_by_step,
            output_dir=ns.output_dir,
            on_step_result=_print_step,
        )

        print(
            json.dumps(
                {
                    "ok": True,
                    "job_id": res.job_id,
                    "results_file": res.results_file,
                    "steps": res.step_results,
                },
                indent=2,
                ensure_ascii=False,
            )
        )

        any_not_completed = any(
            (isinstance(s, dict) and s.get("execution_state") != "COMPLETED")
            for s in (res.step_results or [])
        )
        return 1 if any_not_completed else 0

    raise RuntimeError(f"unknown subcmd: {ns.subcmd}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
