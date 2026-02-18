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


def _notion_title_plain(props: Dict[str, Any], key: str) -> str:
    v = props.get(key) or {}
    rt = v.get("title") if isinstance(v, dict) else None
    if isinstance(rt, list) and rt:
        t0 = rt[0]
        if isinstance(t0, dict):
            txt = t0.get("text")
            if isinstance(txt, dict):
                return str(txt.get("content") or "")
    return ""


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


def _notion_date_start(props: Dict[str, Any], key: str) -> str:
    v = props.get(key) or {}
    dt = v.get("date") if isinstance(v, dict) else None
    if isinstance(dt, dict):
        return str(dt.get("start") or "")
    return ""


def _notion_select_name(props: Dict[str, Any], key: str) -> str:
    v = props.get(key) or {}
    sel = v.get("select") if isinstance(v, dict) else None
    if isinstance(sel, dict):
        return str(sel.get("name") or "")
    return ""


def _notion_relation_id(props: Dict[str, Any], key: str) -> str:
    v = props.get(key) or {}
    rel = v.get("relation") if isinstance(v, dict) else None
    if isinstance(rel, list) and rel:
        r0 = rel[0]
        if isinstance(r0, dict):
            return str(r0.get("id") or "")
    return ""


def test_execute_raw_kreiraj_task_blocks_resolves_goal_once_and_creates_tasks(
    monkeypatch,
):
    app = _load_app()

    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")

    goal_title = "Baza Blok 1 – Adaptacija na trčanje (18.02–02.03)"
    goal_page_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    captured_page_create_payloads: List[Dict[str, Any]] = []
    goals_query_calls = {"count": 0}

    async def fake_safe_request(method: str, url: str, payload=None, params=None):
        # DB schema reads during property build
        if method == "GET" and "/databases/" in url:
            return {"properties": {}}

        # Query goals DB (lookup step)
        if method == "POST" and "/databases/" in url and url.endswith("/query"):
            goals_query_calls["count"] += 1
            return {
                "results": [
                    {
                        "id": goal_page_id,
                        "properties": {"Name": {"title": [{"plain_text": goal_title}]}},
                    }
                ]
            }

        # Task page creates
        if method == "POST" and url.endswith("/pages"):
            captured_page_create_payloads.append(payload or {})
            n = len(captured_page_create_payloads)
            return {
                "id": f"task-page-id-{n}",
                "url": f"https://notion.so/task-page-id-{n}",
            }

        return {}

    prompt = (
        "BATCH: create_task x2 u Tasks DB.\n"
        "Prije kreiranja taskova uradi lookup u Goals DB:\n"
        f'- pronađi page gdje Name == "{goal_title}"\n\n'
        "Kreiraj Task:\n"
        "Name: Trebević hiking – Zona 3\n"
        f"Goal: {goal_title}\n"
        "Due Date: 2026-02-19\n"
        "Priority: high\n"
        "Description: 2–3h hiking, 135–150 bpm, kontrolisano nizbrdo\n\n"
        "Kreiraj Task:\n"
        "Name: 3 km lagano trčanje\n"
        f"Goal: {goal_title}\n"
        "Due Date: 2026-02-21\n"
        "Priority: medium\n"
        "Description: Zona 2, bez forsiranja\n"
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
        mock_update = AsyncMock(return_value=None)
        monkeypatch.setattr(notion, "_update_page_relations", mock_update, raising=True)

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

    intents = [o.get("intent") for o in ops if isinstance(o, dict)]
    assert intents == ["create_task", "create_task"]

    # Ensure we did a single Goals DB lookup for the shared goal title
    assert goals_query_calls["count"] == 1

    # Ensure both tasks were created and field parsing was block-local
    assert len(captured_page_create_payloads) == 2

    p0 = captured_page_create_payloads[0].get("properties") or {}
    p1 = captured_page_create_payloads[1].get("properties") or {}
    assert isinstance(p0, dict)
    assert isinstance(p1, dict)

    # Goal relation must be a UUID and must not be the goal title string.
    rid0 = _notion_relation_id(p0, "Goal")
    rid1 = _notion_relation_id(p1, "Goal")
    assert rid0 == goal_page_id
    assert rid1 == goal_page_id
    assert rid0 != goal_title
    assert rid1 != goal_title
    assert len(rid0.split("-")) == 5

    assert _notion_title_plain(p0, "Name") == "Trebević hiking – Zona 3"
    assert _notion_title_plain(p1, "Name") == "3 km lagano trčanje"

    assert _notion_date_start(p0, "Due Date") == "2026-02-19"
    assert _notion_date_start(p1, "Due Date") == "2026-02-21"

    assert _notion_select_name(p0, "Priority") == "high"
    assert _notion_select_name(p1, "Priority") == "medium"

    d0 = _notion_rich_text_plain(p0, "Description")
    d1 = _notion_rich_text_plain(p1, "Description")
    assert d0 == "2–3h hiking, 135–150 bpm, kontrolisano nizbrdo"
    assert d1 == "Zona 2, bez forsiranja"
    assert "Zona 2" not in d0

    # Relation updates should use resolved UUID, not a title string
    assert mock_update.await_count == 2
    for call in mock_update.await_args_list:
        kwargs = call.kwargs
        assert kwargs.get("goal_id") == goal_page_id
