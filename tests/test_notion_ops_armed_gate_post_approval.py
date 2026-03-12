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
    assert approve_body.get("read_only") is True, approve_body


def test_missing_session_id_blocks_notion_write(monkeypatch):
    """Regression: Notion write must be fail-closed when session_id is missing."""

    import services.execution_orchestrator as eo

    async def _fake_is_armed(_sid: str) -> bool:  # noqa: ANN001
        return True

    monkeypatch.setattr(eo, "notion_ops_is_armed", _fake_is_armed, raising=True)

    app = _load_app()

    with TestClient(app) as client:
        exec_r = client.post(
            "/api/execute/raw",
            json={
                "command": "create_task",
                "intent": "create_task",
                "params": {"title": "T"},
                # metadata intentionally missing session_id
                "metadata": {},
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
    assert approve_body.get("reason") == "notion_ops_session_missing", approve_body


def test_approve_returns_read_only_true_when_blocked(monkeypatch):
    """Contract: BLOCKED due to Notion gate must be read_only=True."""

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
                "metadata": {"session_id": "session-disarmed-2"},
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
    assert approve_body.get("read_only") is True, approve_body


def test_post_approval_allows_notion_write_when_armed_and_session_id_present(
    monkeypatch,
):
    """Green-path: Notion Ops ARMED + valid session_id must not over-block.

    Also confirms the approval resume path reached ExecutionOrchestrator
    `_execute_after_approval()`.
    """

    app = _load_app()

    import routers.ai_ops_router as aor
    import services.execution_orchestrator as eo
    from services.approval_state_service import get_approval_state

    flags: Dict[str, Any] = {"after_approval_hit": False, "notion_execute_called": False}

    class _FakeNotion:
        async def execute(self, command):  # noqa: ANN001
            flags["notion_execute_called"] = True
            return {
                "ok": True,
                "success": True,
                "command": getattr(command, "command", None),
                "intent": getattr(command, "intent", None),
                "result": {"url": "https://notion.so/fake-task"},
            }

    async def _fake_is_armed(_sid: str) -> bool:  # noqa: ANN001
        return True

    monkeypatch.setattr(eo, "notion_ops_is_armed", _fake_is_armed, raising=True)
    monkeypatch.setattr(eo, "get_notion_service", lambda: _FakeNotion(), raising=True)

    approvals = get_approval_state()
    orchestrator = eo.ExecutionOrchestrator()
    orchestrator.approvals = approvals

    orig_after = orchestrator._execute_after_approval

    async def _wrapped_after(cmd):  # noqa: ANN001
        flags["after_approval_hit"] = True
        return await orig_after(cmd)

    monkeypatch.setattr(orchestrator, "_execute_after_approval", _wrapped_after)

    with TestClient(app) as client:
        # App boot may repeatedly inject services; patch accessors so requests
        # always use this instrumented orchestrator and shared approval state.
        monkeypatch.setattr(aor, "_get_orchestrator", lambda: orchestrator, raising=True)
        monkeypatch.setattr(aor, "_get_approval_state", lambda: approvals, raising=True)

        exec_r = client.post(
            "/api/execute/raw",
            json={
                "command": "create_task",
                "intent": "create_task",
                "params": {"title": "T"},
                "metadata": {"session_id": "session-armed-1"},
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

    assert approve_body.get("execution_state") == "COMPLETED", approve_body
    assert approve_body.get("read_only") is False, approve_body
    assert flags["after_approval_hit"] is True
    assert flags["notion_execute_called"] is True

