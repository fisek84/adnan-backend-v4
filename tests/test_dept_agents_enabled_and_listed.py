import json
from pathlib import Path

import pytest

from services.agent_registry_service import AgentRegistryService


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _agents_json_path() -> Path:
    return _repo_root() / "config" / "agents.json"


def test_dept_agents_exist_and_listed_enabled_only() -> None:
    """Operational requirement: dept agents must exist in SSOT and be enabled.

    SSOT source: config/agents.json
    Loader: services/agent_registry_service.py:AgentRegistryService.load_from_agents_json
    Listing API: services/agent_registry_service.py:AgentRegistryService.list_agents(enabled_only=True)

    This test is EXPECTED TO FAIL on the current repo if dept_* agents are missing
    and/or not enabled.
    """

    p = _agents_json_path()
    assert p.is_file(), f"SSOT agents file missing: {p}"

    # Load registry via the canonical SSOT loader.
    reg = AgentRegistryService()
    reg.load_from_agents_json(str(p), clear=True)

    enabled_ids = {a.id for a in reg.list_agents(enabled_only=True)}

    required = {"dept_finance", "dept_growth", "dept_ops", "dept_product"}
    missing = sorted(required - enabled_ids)

    assert not missing, (
        "Dept agents must exist in SSOT and be enabled (listed by list_agents(enabled_only=True)). "
        f"Missing from enabled registry listing: {missing}. "
        "Evidence pointers: config/agents.json; "
        "services/agent_registry_service.py load_from_agents_json + list_agents(enabled_only=True)."
    )
