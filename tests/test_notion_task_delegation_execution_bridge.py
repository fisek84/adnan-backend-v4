from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_snapshot_to_execute_raw_payload_reuses_task_builder_via_preview(monkeypatch):
    """Proof chain: snapshot -> PR#2 preview -> PR#1 builder -> execute/raw payload."""

    from services import notion_delegation_preview_builder
    from services.notion_task_delegation_execution_bridge import (
        build_execute_raw_payload_from_notion_task_snapshot,
    )

    called = {"ok": False}

    def _fake_build_agent_task_from_snapshot(task_item):  # noqa: ANN001
        called["ok"] = True
        assert isinstance(task_item, dict)
        return {
            "task_text": "Task: T\n\nSource: U\n\nDetails:\n- status: s",
            "source_task": {"notion_id": "nid", "url": "U"},
        }

    monkeypatch.setattr(
        notion_delegation_preview_builder,
        "build_agent_task_from_snapshot",
        _fake_build_agent_task_from_snapshot,
        raising=True,
    )

    payload = build_execute_raw_payload_from_notion_task_snapshot(
        task_item={"notion_id": "nid", "title": "T", "url": "U", "fields": {}},
        agent_id=" agent_x ",
        initiator="ceo_chat",
    )

    assert called["ok"] is True

    assert payload.get("command") == "delegate_agent_task"
    assert payload.get("intent") == "delegate_agent_task"
    assert payload.get("read_only") is False
    assert payload.get("initiator") == "ceo_chat"

    params = payload.get("params")
    assert isinstance(params, dict)
    assert params.get("agent_id") == "agent_x"
    assert isinstance(params.get("task_text"), str)


def test_execute_raw_approve_runs_existing_delegate_path_and_no_notion_write(monkeypatch):
    """E2E: execute/raw -> approval -> approve -> delegate execution -> UI contract."""

    # Ensure boot doesn't fail in dev shells.
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")

    # Notion Ops execute must not be called.
    notion_calls: list[object] = []

    async def _fake_notion_execute(self, command):  # noqa: ANN001
        notion_calls.append(command)
        return {"ok": True}

    monkeypatch.setattr(
        "services.notion_ops_agent.NotionOpsAgent.execute",
        _fake_notion_execute,
        raising=True,
    )

    # Stub delegated agent execution pipeline (existing delegate_agent_task path).
    async def _fake_delegate(_cmd):  # noqa: ANN001
        return {
            "ok": True,
            "success": True,
            "intent": "delegate_agent_task",
            "result": {"agent_id": "agent_x", "output_text": "hello"},
        }

    monkeypatch.setattr(
        "services.execution_orchestrator._execute_delegate_agent_task_via_router",
        _fake_delegate,
    )

    from services.notion_task_delegation_execution_bridge import (
        build_execute_raw_payload_from_notion_task_snapshot,
    )

    app = _load_app()
    client = TestClient(app)

    payload = build_execute_raw_payload_from_notion_task_snapshot(
        task_item={"notion_id": "nid", "title": "T", "url": "U", "fields": {}},
        agent_id="agent_x",
        initiator="ceo_chat",
    )

    exec_r = client.post("/api/execute/raw", json=payload)
    assert exec_r.status_code == 200, exec_r.text
    exec_body = exec_r.json()
    assert exec_body.get("execution_state") == "BLOCKED"
    approval_id = exec_body.get("approval_id")
    assert isinstance(approval_id, str) and approval_id.strip()

    approve_r = client.post(
        "/api/ai-ops/approval/approve",
        headers={"X-Initiator": "ceo_chat"},
        json={"approval_id": approval_id, "approved_by": "test"},
    )
    assert approve_r.status_code == 200, approve_r.text
    body = approve_r.json()

    assert body.get("ok") is True
    assert body.get("execution_state") == "COMPLETED"
    assert body.get("approval_id") == approval_id
    assert body.get("text") == "hello"

    inner = body.get("result")
    assert isinstance(inner, dict)
    assert inner.get("agent_id") == "agent_x"
    assert inner.get("output_text") == "hello"

    # No Notion writes on approve/resume delegate path.
    assert notion_calls == []
