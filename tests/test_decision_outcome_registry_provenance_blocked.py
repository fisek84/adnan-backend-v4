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


def test_approve_blocked_execution_must_not_mark_decision_executed(
    monkeypatch, tmp_path
):
    """Regression lock (Block 3): APPROVED but BLOCKED execution must be recorded as not executed."""

    _seed_gateway_env(monkeypatch)
    _isolate_dor_store(monkeypatch, tmp_path)

    app = _load_app()
    client = TestClient(app)

    principal_sub = "dor-provenance-user-1"
    headers = auth_headers(
        None,
        sub=principal_sub,
        roles=["admin"],
        scopes=["raw_execute"],
    )

    # Ensure Notion Ops is DISARMED for this principal.
    toggle = client.post(
        "/api/notion-ops/toggle",
        headers=headers,
        json={"session_id": f"s-{uuid.uuid4().hex}", "armed": False},
    )
    assert toggle.status_code == 200, toggle.text
    assert toggle.json().get("armed") is False

    # Create a Notion write command (requires approval).
    created = client.post(
        "/api/execute/raw",
        headers=headers,
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

    # Approve -> resume execution, which must remain BLOCKED due to Notion Ops gate.
    approved = client.post(
        "/api/ai-ops/approval/approve",
        headers=headers,
        json={"approval_id": approval_id},
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()

    assert approved_body.get("execution_state") == "BLOCKED"
    assert approved_body.get("reason") == "notion_ops_disarmed"
    assert approved_body.get("execution_id") == execution_id

    # DecisionOutcomeRegistry must reflect APPROVED but NOT EXECUTED.
    from services.decision_outcome_registry import get_decision_outcome_registry

    dor = get_decision_outcome_registry()
    rec = dor.get_by_execution_id(execution_id)

    assert isinstance(rec, dict) and rec, "DOR record missing for execution_id"
    assert rec.get("approval_id") == approval_id
    assert rec.get("execution_id") == execution_id

    assert rec.get("accepted") is True
    assert rec.get("executed") is False
    assert rec.get("execution_result") == "not_executed"
    assert rec.get("execution_state") == "BLOCKED"
