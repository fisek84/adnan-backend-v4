from __future__ import annotations

from typing import Any, Dict

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_post_approval_blocks_notion_write_when_disarmed(monkeypatch):
    """Regression: Notion Ops ARMED gate must apply on resume() path.

    Previously the gate existed in ExecutionOrchestrator.execute() only, but
    approvals execute via resume() -> _execute_after_approval().
    """

    import services.execution_orchestrator as eo

    async def _fake_is_armed(_sid: str) -> bool:  # noqa: ANN001
        return False

    monkeypatch.setattr(eo, "notion_ops_is_armed", _fake_is_armed, raising=True)

    app = _load_app()

    with TestClient(app) as client:
        exec_r = client.post(
            "/api/execute/raw",
            json={
                "command": "create_task",
                "intent": "create_task",
                "params": {"title": "T"},
                "metadata": {"session_id": "session-disarmed-1"},
                "initiator": "ceo_chat",
            },
        )
        assert exec_r.status_code == 200, exec_r.text
        exec_body: Dict[str, Any] = exec_r.json()

        approval_id = exec_body.get("approval_id")
        assert isinstance(approval_id, str) and approval_id.strip()

        approve_r = client.post(
            "/api/ai-ops/approval/approve",
            headers={"X-Initiator": "ceo_chat"},
            json={"approval_id": approval_id, "approved_by": "test"},
        )
        assert approve_r.status_code == 200, approve_r.text
        approve_body: Dict[str, Any] = approve_r.json()

    assert approve_body.get("execution_state") == "BLOCKED", approve_body
    assert approve_body.get("reason") == "notion_ops_disarmed", approve_body
