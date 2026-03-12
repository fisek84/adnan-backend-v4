from __future__ import annotations

import re

from fastapi.testclient import TestClient


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def _base_env(monkeypatch):
    # Keep consistent with other deterministic SSOT tests.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")


def _snapshot_with_mixed_statuses():
    return {
        "ready": True,
        "status": "fresh",
        "schema_version": "v1",
        "payload": {
            "goals": [],
            "tasks": [
                {
                    "id": "t1",
                    "title": "Alpha",
                    "status": "Not Started",
                    "due": "-",
                    "priority": "High",
                },
                {
                    "id": "t2",
                    "title": "Beta",
                    "status": "In Progress",
                    "due": "-",
                    "priority": "Low",
                },
                {
                    "id": "t3",
                    "title": "Gamma",
                    "status": "Done",
                    "due": "-",
                    "priority": "-",
                },
            ],
            "projects": [],
        },
    }


def _snapshot_all_completed():
    return {
        "ready": True,
        "status": "fresh",
        "schema_version": "v1",
        "payload": {
            "goals": [],
            "tasks": [
                {
                    "id": "t1",
                    "title": "OnlyDone",
                    "status": "Done",
                    "due": "-",
                    "priority": "-",
                },
                {
                    "id": "t2",
                    "title": "OnlyCompleted",
                    "status": "Completed",
                    "due": "-",
                    "priority": "-",
                },
            ],
            "projects": [],
        },
    }


def test_tasks_phase_a_yes_no_any_tasks_answer_first_and_no_llm(monkeypatch):
    _base_env(monkeypatch)

    async def _llm_called(*_args, **_kwargs):
        raise RuntimeError("CEO Advisor called")

    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router, "create_ceo_advisor_agent", _llm_called, raising=True
    )

    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Da li imamo taskove?",
            "snapshot": _snapshot_with_mixed_statuses(),
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert body.get("agent_id") == "ceo_advisor"

    txt = (body.get("text") or "").strip()
    assert txt.startswith("Da."), txt
    assert "TASKS" not in txt
    assert "Alpha" not in txt
    assert "Beta" not in txt


def test_tasks_phase_a_yes_no_active_tasks_distinguishes_completed_only(monkeypatch):
    _base_env(monkeypatch)

    async def _llm_called(*_args, **_kwargs):
        raise RuntimeError("CEO Advisor called")

    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router, "create_ceo_advisor_agent", _llm_called, raising=True
    )

    app = _get_app()
    client = TestClient(app)
    snap = _snapshot_all_completed()

    r_any = client.post(
        "/api/chat",
        json={"message": "Da li imamo taskove?", "snapshot": snap},
    )
    assert r_any.status_code == 200, r_any.text
    txt_any = (r_any.json().get("text") or "").strip()
    assert txt_any.startswith("Da."), txt_any

    r_active = client.post(
        "/api/chat",
        json={"message": "Da li imamo aktivne taskove?", "snapshot": snap},
    )
    assert r_active.status_code == 200, r_active.text
    txt_active = (r_active.json().get("text") or "").strip()
    assert txt_active.startswith("Ne."), txt_active


def test_tasks_phase_a_count_tasks_starts_with_number(monkeypatch):
    _base_env(monkeypatch)

    async def _llm_called(*_args, **_kwargs):
        raise RuntimeError("CEO Advisor called")

    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router, "create_ceo_advisor_agent", _llm_called, raising=True
    )

    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Koliko taskova imamo?",
            "snapshot": _snapshot_with_mixed_statuses(),
        },
    )
    assert r.status_code == 200, r.text

    txt = (r.json().get("text") or "").strip()
    assert re.match(r"^\d+", txt), txt
    assert "Alpha" not in txt
    assert "Beta" not in txt


def test_tasks_phase_a_status_is_breakdown_not_list(monkeypatch):
    _base_env(monkeypatch)

    async def _llm_called(*_args, **_kwargs):
        raise RuntimeError("CEO Advisor called")

    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router, "create_ceo_advisor_agent", _llm_called, raising=True
    )

    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Status taskova?",
            "snapshot": _snapshot_with_mixed_statuses(),
        },
    )
    assert r.status_code == 200, r.text

    txt = (r.json().get("text") or "").strip()

    # STATUS: must not list titles or include list headers.
    assert "TASKS" not in txt
    assert "Alpha" not in txt
    assert "Beta" not in txt

    # Must include breakdown marker.
    assert "po statusu" in txt.lower(), txt


def test_tasks_phase_a_list_vs_status_separation(monkeypatch):
    _base_env(monkeypatch)

    async def _llm_called(*_args, **_kwargs):
        raise RuntimeError("CEO Advisor called")

    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router, "create_ceo_advisor_agent", _llm_called, raising=True
    )

    app = _get_app()
    client = TestClient(app)

    snap = _snapshot_with_mixed_statuses()

    r_list = client.post(
        "/api/chat",
        json={"message": "Pokazi taskove po statusu", "snapshot": snap},
    )
    assert r_list.status_code == 200, r_list.text
    txt_list = r_list.json().get("text") or ""

    # LIST path should show a TASKS header and include at least one title.
    assert "TASKS" in txt_list or "tasks" in txt_list.lower()
    assert "Alpha" in txt_list

    r_status = client.post(
        "/api/chat",
        json={"message": "Status taskova?", "snapshot": snap},
    )
    assert r_status.status_code == 200, r_status.text
    txt_status = r_status.json().get("text") or ""

    # STATUS path must not include titles.
    assert "Alpha" not in txt_status
