from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _count_pending_agent_result_notion_approvals(state) -> int:  # noqa: ANN001
    pending = state.list_pending()
    n = 0
    for a in pending:
        if not isinstance(a, dict):
            continue
        if (a.get("command") or "") != "notion_write":
            continue
        n += 1
    return n


def test_agent_result_without_notion_write(monkeypatch):
    """If the delegated agent does not request a Notion write, no new approval is created."""

    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")

    # Stub NotionOpsAgent.execute: must not be called in this test.
    calls: list[object] = []

    async def _fake_notion_execute(self, command):  # noqa: ANN001
        calls.append(command)
        return {"ok": True, "success": True, "intent": getattr(command, "intent", None)}

    monkeypatch.setattr(
        "services.notion_ops_agent.NotionOpsAgent.execute",
        _fake_notion_execute,
        raising=True,
    )

    # Stub delegated agent execution pipeline.
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

    from services.approval_state_service import get_approval_state

    state = get_approval_state()
    before_n = _count_pending_agent_result_notion_approvals(state)

    app = _load_app()
    client = TestClient(app)

    exec_r = client.post(
        "/api/execute/raw",
        json={
            "command": "delegate_agent_task",
            "intent": "delegate_agent_task",
            "params": {"agent_id": "agent_x", "task_text": "Say hello"},
            "payload_summary": {},
            "initiator": "ceo_chat",
        },
    )
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

    # Delegate execution result contract
    assert body.get("ok") is True
    assert body.get("execution_state") == "COMPLETED"
    assert isinstance(body.get("execution_id"), str) and body.get("execution_id")
    assert body.get("approval_id") == approval_id

    inner = body.get("result")
    assert isinstance(inner, dict)
    assert inner.get("agent_id") == "agent_x"
    assert inner.get("output_text") == "hello"
    assert body.get("pending_approval") is None
    assert body.get("pending_next_action") is None

    after_n = _count_pending_agent_result_notion_approvals(state)
    assert after_n == before_n
    assert len(calls) == 0


def test_agent_result_with_notion_write_returns_pending_next_action(monkeypatch):
    """If delegated agent requests a Notion write, backend returns a proposal but creates no approvals."""

    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")

    notion_calls: list[object] = []

    async def _fake_notion_execute(self, command):  # noqa: ANN001
        notion_calls.append(command)
        return {
            "ok": True,
            "success": True,
            "intent": getattr(command, "intent", None),
            "result": {"stub": True},
        }

    monkeypatch.setattr(
        "services.notion_ops_agent.NotionOpsAgent.execute",
        _fake_notion_execute,
        raising=True,
    )

    async def _fake_delegate(_cmd):  # noqa: ANN001
        return {
            "ok": True,
            "success": True,
            "intent": "delegate_agent_task",
            "result": {
                "agent_id": "agent_x",
                "output_text": "Need to write to Notion",
                "requires_notion_write": True,
                "notion_proposal": {
                    "intent": "create_task",
                    "params": {"title": "Follow up", "priority": "high"},
                },
            },
        }

    monkeypatch.setattr(
        "services.execution_orchestrator._execute_delegate_agent_task_via_router",
        _fake_delegate,
    )

    from services.approval_state_service import get_approval_state

    state = get_approval_state()
    before_n = _count_pending_agent_result_notion_approvals(state)

    app = _load_app()
    client = TestClient(app)

    exec_r = client.post(
        "/api/execute/raw",
        json={
            "command": "delegate_agent_task",
            "intent": "delegate_agent_task",
            "params": {
                "agent_id": "agent_x",
                "task_text": "Please propose Notion task",
            },
            "payload_summary": {},
            "initiator": "ceo_chat",
        },
    )
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
    res = body.get("result")
    assert isinstance(res, dict)
    assert res.get("requires_notion_write") is True
    assert isinstance(res.get("notion_proposal"), dict)

    assert body.get("pending_approval") is None

    nxt = body.get("pending_next_action")
    assert isinstance(nxt, dict)
    assert nxt.get("endpoint") == "/api/execute/preview"
    assert nxt.get("command") == "notion_write"
    assert nxt.get("intent") == "create_task"
    assert isinstance(nxt.get("params"), dict)
    assert nxt.get("read_only") is True

    after_n = _count_pending_agent_result_notion_approvals(state)
    assert after_n == before_n

    # The approve/resume path must not execute Notion.
    assert len(notion_calls) == 0
