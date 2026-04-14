from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from tests.auth_utils import auth_headers


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _set_minimal_notion_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Gateway boot requires these env vars (init_notion_service_from_env_or_raise).
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-token")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "db-goals")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "db-tasks")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "db-projects")

    # Avoid boot-time knowledge sync attempting any HTTP.
    monkeypatch.setenv("GATEWAY_SKIP_KNOWLEDGE_SYNC", "1")


def _stub_notion_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deterministic stub for the external Notion API call.
    # IMPORTANT: This does not bypass gateway/orchestrator/auth/approval/gating.
    from services.notion_service import NotionService

    async def _fake_execute(self: NotionService, ai_command: Any) -> Dict[str, Any]:
        return {
            "ok": True,
            "success": True,
            "intent": getattr(ai_command, "intent", None),
            "command": getattr(ai_command, "command", None),
            "result": {"url": "https://notion.so/fake"},
        }

    monkeypatch.setattr(NotionService, "execute", _fake_execute, raising=True)


def _execute_raw_create_task(
    client: TestClient, *, principal_sub: str, session_id: str
) -> Dict[str, Any]:
    exec_r = client.post(
        "/api/execute/raw",
        headers=auth_headers(
            None,
            sub=principal_sub,
            roles=["ceo"],
            scopes=["raw_execute"],
            extra={"X-Initiator": "ceo_chat"},
        ),
        json={
            "command": "create_task",
            "intent": "create_task",
            "params": {"title": "T"},
            "metadata": {
                "session_id": session_id,
                "principal_sub": principal_sub,
            },
        },
    )
    assert exec_r.status_code == 200, exec_r.text
    body: Dict[str, Any] = exec_r.json()

    approval_id = body.get("approval_id")
    assert isinstance(approval_id, str) and approval_id.strip(), body
    return body


def _approve(
    client: TestClient, *, approval_id: str, approver_sub: str = "approver-1"
) -> Dict[str, Any]:
    approve_r = client.post(
        "/api/ai-ops/approval/approve",
        headers=auth_headers(
            None,
            sub=approver_sub,
            roles=["ops_approver"],
            extra={"X-Initiator": "ceo_chat"},
        ),
        json={"approval_id": approval_id, "approved_by": "test"},
    )
    assert approve_r.status_code == 200, approve_r.text
    return approve_r.json()


def _toggle(
    client: TestClient, *, principal_sub: str, session_id: str, armed: bool
) -> Dict[str, Any]:
    r = client.post(
        "/api/notion-ops/toggle",
        headers=auth_headers(None, sub=principal_sub, roles=["ceo"]),
        json={"session_id": session_id, "armed": armed},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_toggle_armed_must_allow_post_approval_notion_write(monkeypatch, tmp_path):
    """Regression lock (Block 1): /api/notion-ops/toggle MUST affect post-approval Notion writes.

    This test is expected to FAIL on the current repo state because toggle
    persists to notion_armed_store, while the orchestrator gate checks the
    in-memory services.notion_ops_state SSOT.
    """

    _set_minimal_notion_env(monkeypatch)
    monkeypatch.setenv("NOTION_ARMED_STORE_PATH", str(tmp_path / "armed.json"))
    _stub_notion_execute(monkeypatch)

    app = _load_app()
    principal_sub = "nops-toggle-armed-user-1"
    session_id = "nops-toggle-armed-session-1"

    with TestClient(app) as client:
        toggle_body = _toggle(
            client,
            principal_sub=principal_sub,
            session_id=session_id,
            armed=True,
        )
        assert toggle_body.get("armed") is True, toggle_body

        exec_body = _execute_raw_create_task(
            client, principal_sub=principal_sub, session_id=session_id
        )
        approval_id = exec_body.get("approval_id")
        assert isinstance(approval_id, str) and approval_id.strip()

        approve_body = _approve(client, approval_id=approval_id)

    # Expected contract after SSOT unification:
    # - execution must not be BLOCKED
    # - read_only must be False
    assert approve_body.get("execution_state") != "BLOCKED", approve_body
    assert approve_body.get("read_only") is not True, approve_body


def test_toggle_disarmed_must_block_post_approval_notion_write(monkeypatch, tmp_path):
    """Negative case (required): DISARMED must BLOCK post-approval Notion writes."""

    _set_minimal_notion_env(monkeypatch)
    monkeypatch.setenv("NOTION_ARMED_STORE_PATH", str(tmp_path / "armed.json"))
    _stub_notion_execute(monkeypatch)

    app = _load_app()
    principal_sub = "nops-toggle-disarmed-user-1"
    session_id = "nops-toggle-disarmed-session-1"

    with TestClient(app) as client:
        toggle_body = _toggle(
            client,
            principal_sub=principal_sub,
            session_id=session_id,
            armed=False,
        )
        assert toggle_body.get("armed") is False, toggle_body

        exec_body = _execute_raw_create_task(
            client, principal_sub=principal_sub, session_id=session_id
        )
        approval_id = exec_body.get("approval_id")
        assert isinstance(approval_id, str) and approval_id.strip()

        approve_body = _approve(client, approval_id=approval_id)

    assert approve_body.get("execution_state") == "BLOCKED", approve_body
    assert approve_body.get("read_only") is True, approve_body
