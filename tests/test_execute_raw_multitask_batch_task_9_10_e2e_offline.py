from __future__ import annotations

from typing import Any, Dict, List

from fastapi.testclient import TestClient
from unittest.mock import AsyncMock


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _notion_rich_text_plain(props: Dict[str, Any], key: str) -> str:
    v = props.get(key) or {}
    rt = v.get("rich_text") if isinstance(v, dict) else None
    if isinstance(rt, list) and rt:
        t0 = rt[0]
        if isinstance(t0, dict):
            txt = t0.get("text")
            if isinstance(txt, dict):
                return str(txt.get("content") or "")
    return ""


def _contains_key_recursive(x: Any, needle_key: str) -> bool:
    if isinstance(x, dict):
        for k, v in x.items():
            if isinstance(k, str) and k == needle_key:
                return True
            if _contains_key_recursive(v, needle_key):
                return True
        return False
    if isinstance(x, list):
        return any(_contains_key_recursive(v, needle_key) for v in x)
    return False


def test_execute_raw_multitask_blocks_task_9_10_approve_executes_batch_and_returns_urls(
    monkeypatch,
):
    app = _load_app()

    # Deterministic dummy env vars (gateway startup initializes NotionService from env).
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")

    captured_page_create_payloads: List[Dict[str, Any]] = []
    created = {"count": 0}

    async def fake_safe_request(method: str, url: str, payload=None, params=None):
        # DB schema reads during property build.
        if method == "GET" and "/databases/" in url:
            return {"properties": {}}

        # Task page creates.
        if method == "POST" and url.endswith("/pages"):
            created["count"] += 1
            captured_page_create_payloads.append(payload or {})
            n = created["count"]
            return {
                "id": f"task-page-id-{n}",
                "url": f"https://notion.so/task-page-id-{n}",
            }

        return {}

    prompt = (
        "kreiraj taskove:\n"
        "Task 9\n"
        "Name: Deveto\n"
        "Description: Opis 9\n"
        "\n"
        "Task 10\n"
        "Name: Deseto\n"
        "Description: Opis 10\n"
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
        assert approve_r.status_code == 200, approve_r.text
        approve_body = approve_r.json()

    # (1) execute returns batch_request with exactly 2 operations
    assert approve_body.get("execution_state") == "COMPLETED", approve_body

    result = approve_body.get("result")
    assert isinstance(result, dict)
    assert result.get("ok") is True

    inner = result.get("result")
    assert isinstance(inner, dict)
    assert inner.get("intent") == "batch_request"

    ops = inner.get("operations")
    assert isinstance(ops, list)
    assert len(ops) == 2

    # (2) stable op_id/client_ref = task_9, task_10 (in that order)
    op_ids = [str(o.get("op_id") or "") for o in ops if isinstance(o, dict)]
    assert op_ids == ["task_9", "task_10"], ops

    for op in ops:
        assert isinstance(op, dict)
        assert op.get("client_ref") == op.get("op_id")
        # (3) each op has non-empty url
        assert isinstance(op.get("url"), str) and op.get("url")

        # (5) supports_bilingual must not appear in task operation payload/result
        assert not _contains_key_recursive(op, "supports_bilingual"), op

    # (4) no Description bleed, proven by inspecting the Notion page-create payloads
    assert len(captured_page_create_payloads) == 2

    p0 = captured_page_create_payloads[0]
    p1 = captured_page_create_payloads[1]

    # (5) supports_bilingual must not appear anywhere in the outgoing tasks DB payload
    assert not _contains_key_recursive(p0, "supports_bilingual"), p0
    assert not _contains_key_recursive(p1, "supports_bilingual"), p1

    props0 = p0.get("properties") or {}
    props1 = p1.get("properties") or {}
    assert isinstance(props0, dict)
    assert isinstance(props1, dict)

    d0 = _notion_rich_text_plain(props0, "Description")
    d1 = _notion_rich_text_plain(props1, "Description")

    assert d0.strip() == "Opis 9"
    assert d1.strip() == "Opis 10"
    assert "Opis 10" not in d0
    assert "Opis 9" not in d1
