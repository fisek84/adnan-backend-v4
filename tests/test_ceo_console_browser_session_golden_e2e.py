from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from models.agent_contract import AgentOutput, ProposedCommand


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _disable_grounding(monkeypatch) -> None:
    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )


def _snapshot_payload() -> Dict[str, Any]:
    return {"payload": {"tasks": [], "goals": [], "projects": []}}


def _title_text_from_props_preview(props_preview: Dict[str, Any]) -> str:
    name = props_preview.get("Name") or props_preview.get("Project Name") or {}
    title = name.get("title") if isinstance(name, dict) else None
    if isinstance(title, list) and title:
        t0 = title[0]
        if isinstance(t0, dict):
            txt = t0.get("text")
            if isinstance(txt, dict):
                return str(txt.get("content") or "")
    return ""


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


def test_ceo_console_browser_session_golden_flow_plan_to_preview_arm_create_approve(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_console_browser_session_golden_state.json"),
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")
    _disable_grounding(monkeypatch)

    app = _load_app()

    session_id = "golden-browser-session-1"
    goal_page_id = "goal-page-id-golden-1"
    captured: Dict[str, Any] = {}
    captured_page_create_payloads: List[Dict[str, Any]] = []

    plan_text = (
        'Kreiraj centralni cilj "Implementirati KPI OS" sa due date 15.06.2025, '
        "prioritet Visok, status Aktivan. "
        "Kreiraj 7-dnevni plan taskova: "
        "Dan 1: KPI plan (Visok) "
        "Dan 2: Mapirati metrike (Visok) "
        "Dan 3: Postaviti dashboard (Visok) "
        "Dan 4: Povezati podatke (Srednji) "
        "Dan 5: Testirati izvještaje (Srednji) "
        "Dan 6: Refinirati KPI (Visok) "
        "Dan 7: Finalna provjera (Visok)"
    )

    expected_task_titles = [
        "KPI plan",
        "Mapirati metrike",
        "Postaviti dashboard",
        "Povezati podatke",
        "Testirati izvještaje",
        "Refinirati KPI",
        "Finalna provjera",
    ]

    async def _fake_ceo_advisor_agent(_payload, _ctx):  # noqa: ANN001
        return AgentOutput(
            text=plan_text,
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"stub": True},
        )

    async def _fake_notion_ops_agent(_payload, ctx=None):  # noqa: ANN001
        resolved_prompt = getattr(_payload, "message", "")
        captured["resolved_prompt"] = resolved_prompt
        return AgentOutput(
            text="stub notion proposal",
            proposed_commands=[
                ProposedCommand(
                    command="ceo.command.propose",
                    params={"prompt": resolved_prompt, "supports_bilingual": True},
                    reason="Golden browser-session proposal",
                    dry_run=True,
                    requires_approval=True,
                    risk="LOW",
                    scope="api_execute_raw",
                )
            ],
            agent_id="notion_ops",
            read_only=True,
            trace={"stub": True},
        )

    monkeypatch.setattr(
        "routers.chat_router.create_ceo_advisor_agent",
        _fake_ceo_advisor_agent,
        raising=True,
    )
    monkeypatch.setattr(
        "services.notion_ops_agent.notion_ops_agent",
        _fake_notion_ops_agent,
        raising=True,
    )

    with TestClient(app) as notion_client:
        from services.notion_service import get_notion_service  # noqa: PLC0415

        notion = get_notion_service()

        async def fake_safe_request(method: str, url: str, payload=None, params=None):
            if method == "GET" and "/databases/" in url:
                return {"properties": {}}

            if method == "POST" and url.endswith("/pages"):
                payload0 = payload or {}
                captured_page_create_payloads.append(payload0)
                idx = len(captured_page_create_payloads)
                page_id = goal_page_id if idx == 1 else f"task-page-id-{idx - 1}"
                return {
                    "id": page_id,
                    "url": f"https://notion.so/{page_id}",
                }

            return {}

        mock_update = AsyncMock(return_value=None)
        monkeypatch.setattr(
            notion,
            "_safe_request",
            AsyncMock(side_effect=fake_safe_request),
            raising=True,
        )
        monkeypatch.setattr(notion, "_update_page_relations", mock_update, raising=True)

        advisory_r = notion_client.post(
            "/api/chat",
            json={
                "message": "Napiši sedmodnevni KPI implementacioni plan.",
                "session_id": session_id,
                "snapshot": _snapshot_payload(),
                "metadata": {"include_debug": True, "initiator": "ceo_chat"},
            },
        )
        assert advisory_r.status_code == 200, advisory_r.text

        advisory_body = advisory_r.json()
        assert advisory_body.get("read_only") is True
        assert advisory_body.get("text") == plan_text
        assert advisory_body.get("proposed_commands") == []

        transform_r = notion_client.post(
            "/api/chat",
            json={
                "message": (
                    "Pretvori ovaj plan u jedan goal i sedam taskova, "
                    "poveži taskove sa goalom, status Active, priority Medium, "
                    "daj mi preview za Notion upis, nemoj izvršiti:\n"
                    'Kreiraj centralni cilj "POGRESAN IZVOR".\n'
                    "Dan 1: Ovo ne smije biti korišteno"
                ),
                "session_id": session_id,
                "snapshot": _snapshot_payload(),
                "metadata": {"include_debug": True, "initiator": "ceo_chat"},
            },
        )
        assert transform_r.status_code == 200, transform_r.text

        transform_body = transform_r.json()
        resolved_prompt = captured.get("resolved_prompt") or ""
        assert "Implementirati KPI OS" in resolved_prompt
        assert "Dan 7: Finalna provjera" in resolved_prompt
        assert "POGRESAN IZVOR" not in resolved_prompt
        assert "Ovo ne smije biti korišteno" not in resolved_prompt

        trace = transform_body.get("trace") or {}
        plan_trace = trace.get("plan_transform_source") or {}
        assert plan_trace.get("source") == "session_last_relevant"

        assert transform_body.get("read_only") is True
        assert (
            transform_body.get("text")
            == "Structured preview je spreman. Nema izvršenja."
        )

        pcs = transform_body.get("proposed_commands") or []
        assert isinstance(pcs, list) and len(pcs) == 1
        proposal = pcs[0]
        proposal_params = proposal.get("params") or proposal.get("args") or {}
        assert proposal.get("command") == "ceo.command.propose"
        assert proposal_params.get("prompt") == resolved_prompt

        cmd = transform_body.get("command") or {}
        assert cmd.get("command") == "notion_write"
        assert cmd.get("intent") == "batch_request"

        notion_preview = transform_body.get("notion") or {}
        assert notion_preview.get("type") == "batch_preview"
        rows = notion_preview.get("rows") or []
        assert isinstance(rows, list)

        goal_rows = [
            row
            for row in rows
            if isinstance(row, dict) and row.get("intent") == "create_goal"
        ]
        task_rows = [
            row
            for row in rows
            if isinstance(row, dict) and row.get("intent") == "create_task"
        ]
        assert len(goal_rows) == 1
        assert len(task_rows) == 7

        goal_title = _title_text_from_props_preview(
            goal_rows[0].get("properties_preview") or {}
        )
        assert goal_title == "Implementirati KPI OS"
        assert goal_title != "Untitled"

        task_titles = [
            _title_text_from_props_preview(row.get("properties_preview") or {})
            for row in task_rows
        ]
        assert task_titles == expected_task_titles
        for row in task_rows:
            assert str(row.get("Goal Ref") or "").startswith("ref:")

        armed_r = notion_client.post(
            "/api/chat",
            json={
                "message": "notion ops aktiviraj",
                "session_id": session_id,
                "metadata": {"session_id": session_id, "initiator": "ceo_chat"},
            },
        )
        assert armed_r.status_code == 200, armed_r.text

        armed_body = armed_r.json()
        assert armed_body.get("notion_ops", {}).get("armed") is True

        exec_r = notion_client.post(
            "/api/execute/raw",
            headers={"X-Initiator": "ceo_chat"},
            json={
                "command": proposal.get("command"),
                "intent": proposal.get("intent") or proposal.get("command"),
                "params": dict(proposal_params),
                "session_id": session_id,
                "metadata": {"session_id": session_id},
                "payload_summary": proposal.get("payload_summary") or {},
            },
        )
        assert exec_r.status_code == 200, exec_r.text

        exec_body = exec_r.json()
        approval_id = exec_body.get("approval_id")
        assert isinstance(approval_id, str) and approval_id.strip()

        approve_r = notion_client.post(
            "/api/ai-ops/approval/approve",
            headers={"X-Initiator": "ceo_chat"},
            json={"approval_id": approval_id, "session_id": session_id},
        )
        assert approve_r.status_code == 200, approve_r.text

        approve_body = approve_r.json()

    assert approve_body.get("execution_state") == "COMPLETED", approve_body
    assert approve_body.get("read_only") is False, approve_body

    result = approve_body.get("result")
    assert isinstance(result, dict)
    assert result.get("ok") is True

    inner = result.get("result")
    assert isinstance(inner, dict)
    assert inner.get("intent") == "batch_request"

    operations = inner.get("operations")
    assert isinstance(operations, list)
    assert len(operations) == 8

    op_intents = [op.get("intent") for op in operations if isinstance(op, dict)]
    assert op_intents == ["create_goal", *(["create_task"] * 7)]

    assert len(captured_page_create_payloads) == 8
    goal_props = captured_page_create_payloads[0].get("properties") or {}
    assert _notion_title_plain(goal_props, "Name") == "Implementirati KPI OS"

    task_payload_titles = [
        _notion_title_plain((payload.get("properties") or {}), "Name")
        for payload in captured_page_create_payloads[1:]
    ]
    assert task_payload_titles == expected_task_titles

    assert mock_update.await_count == 7
    for call in mock_update.await_args_list:
        kwargs = call.kwargs
        assert kwargs.get("goal_id") == goal_page_id
        assert isinstance(kwargs.get("page_id"), str)
        assert kwargs.get("page_id")
