import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _agents_json() -> dict:
    p = _repo_root() / "config" / "agents.json"
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_dept_agent_job_contract_present_in_ssot() -> None:
    """Operational requirement: dept agents have canonical job contracts in SSOT.

    Required per dept_* agent:
    - role
    - job_contract: does/does_not/input/output/approval_rule/notion_ops_write_rule
    - output_schema keys: summary, evidence_links, next_actions, needs_approval

    This test is EXPECTED TO FAIL on the current repo.
    """

    data = _agents_json()
    agents = data.get("agents") if isinstance(data, dict) else None
    assert isinstance(agents, list), "config/agents.json missing agents[]"

    by_id = {}
    for a in agents:
        if isinstance(a, dict) and isinstance(a.get("id"), str):
            by_id[a["id"]] = a

    required_ids = ["dept_finance", "dept_growth", "dept_ops", "dept_product"]

    missing_agents = [aid for aid in required_ids if aid not in by_id]
    assert not missing_agents, (
        "Dept agents missing from SSOT config/agents.json: "
        f"{missing_agents}. "
        "(Expected to fail until dept agents + contracts are added.)"
    )

    required_job_contract_keys = {
        "does",
        "does_not",
        "input",
        "output",
        "approval_rule",
        "notion_ops_write_rule",
    }
    required_output_schema_keys = {
        "summary",
        "evidence_links",
        "next_actions",
        "needs_approval",
    }

    errors = []
    for aid in required_ids:
        a = by_id[aid]

        if not isinstance(a.get("role"), str) or not a.get("role").strip():
            errors.append(f"{aid}: missing role")

        jc = a.get("job_contract")
        if not isinstance(jc, dict):
            errors.append(f"{aid}: missing job_contract")
        else:
            missing = sorted(required_job_contract_keys - set(jc.keys()))
            if missing:
                errors.append(f"{aid}: job_contract missing keys {missing}")

        oschema = a.get("output_schema")
        if not isinstance(oschema, dict):
            errors.append(f"{aid}: missing output_schema")
        else:
            missing = sorted(required_output_schema_keys - set(oschema.keys()))
            if missing:
                errors.append(f"{aid}: output_schema missing keys {missing}")

    assert not errors, "Dept agent SSOT contract violations:\n- " + "\n- ".join(errors)
