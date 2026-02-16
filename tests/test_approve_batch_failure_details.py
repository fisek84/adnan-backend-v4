from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_approve_batch_failure_returns_op_id_and_reason(monkeypatch):
    app = _load_app()

    # Ensure boot doesn't fail in dev shells.
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")

    created = {"count": 0}

    async def fake_safe_request(method: str, url: str, payload=None, params=None):
        # DB schema reads during property build.
        if method == "GET" and "/databases/" in url:
            return {"properties": {}}

        # Task page creates.
        if method == "POST" and url.endswith("/pages"):
            if created["count"] == 0:
                created["count"] += 1
                raise RuntimeError(
                    'Notion HTTP 400: {"code":"validation_error","message":"Property \\\"Level\\\" is invalid"}'
                )
            created["count"] += 1
            n = created["count"]
            return {
                "id": f"task-page-id-{n}",
                "url": f"https://notion.so/task-page-id-{n}",
            }

        return {}

    prompt = (
        "kreiraj taskove:\n"
        "Task 1\n"
        "Name: Prvi\n"
        "Description: Opis 1\n"
        "\n"
        "Task 2\n"
        "Name: Drugi\n"
        "Description: Opis 2\n"
    )

    with TestClient(app) as client:
        from services.notion_service import get_notion_service  # noqa: PLC0415

        notion = get_notion_service()
        monkeypatch.setattr(
            notion,
            "_safe_request",
            AsyncMock(side_effect=fake_safe_request),
            raising=True,
        )
        monkeypatch.setattr(
            notion,
            "_update_page_relations",
            AsyncMock(return_value=None),
            raising=True,
        )

        # Create approval via execute/raw
        exec_r = client.post(
            "/api/execute/raw",
            json={
                "command": "ceo.command.propose",
                "intent": "ceo.command.propose",
                "params": {"prompt": prompt, "supports_bilingual": True},
                "payload_summary": {},
                "initiator": "ceo_chat",
            },
        )
        assert exec_r.status_code == 200, exec_r.text

        approval_id = exec_r.json().get("approval_id")
        assert isinstance(approval_id, str) and approval_id.strip()

        approve_r = client.post(
            "/api/ai-ops/approval/approve",
            headers={"X-Initiator": "ceo_chat"},
            json={"approval_id": approval_id, "approved_by": "test"},
        )

        assert approve_r.status_code == 422, approve_r.text
        body = approve_r.json()

    assert body.get("execution_id"), body
    assert body.get("failed_op_id") in {"task_1", "task_2"}, body

    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip()
    assert "Execution failed" not in msg, body

    op_results = body.get("op_results")
    assert isinstance(op_results, list) and op_results, body

    rec1 = next(
        (
            r
            for r in op_results
            if isinstance(r, dict) and (r.get("op_id") or "") == "task_1"
        ),
        None,
    )
    assert isinstance(rec1, dict), op_results
    assert rec1.get("ok") is False

    reason = rec1.get("reason")
    assert isinstance(reason, str) and "Notion HTTP 400" in reason
    assert "validation_error" in reason

    status_code = rec1.get("status_code")
    assert status_code == 400
