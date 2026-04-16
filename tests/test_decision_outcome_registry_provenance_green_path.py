from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.auth_utils import auth_headers


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _seed_gateway_env(monkeypatch) -> None:
    # Keep boot deterministic/offline.
    monkeypatch.setenv("GATEWAY_SKIP_KNOWLEDGE_SYNC", "1")

    # Minimal Notion env required by boot paths used in execute/raw tests.
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")


def _isolate_dor_store(monkeypatch, tmp_path) -> None:
    import services.decision_outcome_registry as dor_mod

    monkeypatch.setattr(
        dor_mod,
        "_REGISTRY_FILE",
        tmp_path / "decision_outcomes.json",
        raising=True,
    )
    monkeypatch.setattr(
        dor_mod,
        "_DECISION_OUTCOME_REGISTRY_SINGLETON",
        None,
        raising=True,
    )


def _stub_notion_execute(monkeypatch) -> None:
    # Deterministic stub for the external Notion API call.
    # IMPORTANT: This does not bypass gateway/orchestrator/auth/approval/DOR.
    from services.notion_service import NotionService

    async def _fake_execute(self: NotionService, ai_command):
        return {
            "ok": True,
            "success": True,
            "intent": getattr(ai_command, "intent", None),
            "command": getattr(ai_command, "command", None),
            "result": {"url": "https://notion.so/fake"},
        }

    monkeypatch.setattr(NotionService, "execute", _fake_execute, raising=True)


def test_green_path_records_provenance_in_decision_outcome_registry(
    monkeypatch, tmp_path
):
    """Regression lock (Block 3): successful execution must write full provenance to DOR.

    Canon asserted here:
    - approval_id/execution_id linkage is preserved
    - executed==True on real execution
    - execution_result matches actual outcome
    - principal_sub is the authenticated /api/execute/raw principal (initiator)
    """

    _seed_gateway_env(monkeypatch)
    _isolate_dor_store(monkeypatch, tmp_path)
    monkeypatch.setenv("NOTION_ARMED_STORE_PATH", str(tmp_path / "armed.json"))
    _stub_notion_execute(monkeypatch)

    app = _load_app()
    client = TestClient(app)

    initiator_sub = "dor-green-initiator-1"
    approver_sub = "dor-green-approver-1"

    initiator_headers = auth_headers(
        None,
        sub=initiator_sub,
        roles=["admin"],
        scopes=["raw_execute"],
    )

    # Ensure Notion Ops is ARMED for the initiating principal (so resume is not BLOCKED).
    toggle = client.post(
        "/api/notion-ops/toggle",
        headers=initiator_headers,
        json={"session_id": f"s-{uuid.uuid4().hex}", "armed": True},
    )
    assert toggle.status_code == 200, toggle.text
    assert toggle.json().get("armed") is True

    # 1) Execute/raw -> approval created (BLOCKED) + ids.
    created = client.post(
        "/api/execute/raw",
        headers=initiator_headers,
        json={
            "command": "create_task",
            "intent": "create_task",
            "params": {"title": "Test"},
            "metadata": {"session_id": f"s-{uuid.uuid4().hex}"},
        },
    )
    assert created.status_code == 200, created.text
    created_body = created.json()
    assert created_body.get("execution_state") == "BLOCKED"

    approval_id = created_body.get("approval_id")
    execution_id = created_body.get("execution_id")
    assert isinstance(approval_id, str) and approval_id.strip()
    assert isinstance(execution_id, str) and execution_id.strip()

    # 2) Approve -> execution resumes and should complete (not blocked).
    approved = client.post(
        "/api/ai-ops/approval/approve",
        headers=auth_headers(
            None,
            sub=approver_sub,
            roles=["ops_approver"],
        ),
        json={"approval_id": approval_id},
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()

    assert approved_body.get("execution_id") == execution_id
    assert approved_body.get("execution_state") == "COMPLETED", approved_body

    # 3) DecisionOutcomeRegistry must contain the full provenance for this execution.
    from services.decision_outcome_registry import get_decision_outcome_registry

    dor = get_decision_outcome_registry()
    rec = dor.get_by_execution_id(execution_id)

    assert isinstance(rec, dict) and rec, "DOR record missing for execution_id"

    assert rec.get("approval_id") == approval_id
    assert rec.get("execution_id") == execution_id

    assert rec.get("executed") is True

    execution_result = rec.get("execution_result")
    assert isinstance(execution_result, str) and execution_result.strip()

    # Must match actual execution outcome.
    if approved_body.get("execution_state") == "COMPLETED":
        assert execution_result == "success"
    elif approved_body.get("execution_state") == "FAILED":
        assert execution_result == "fail"

    # Principal provenance: must match the authenticated /api/execute/raw principal.
    assert rec.get("principal_sub") == initiator_sub
