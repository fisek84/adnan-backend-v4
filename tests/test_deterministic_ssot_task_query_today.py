from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def _ready_snapshot_today_and_tomorrow():
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    return {
        "ready": True,
        "status": "fresh",
        "schema_version": "v1",
        "payload": {
            "goals": [],
            "tasks": [
                {
                    "id": "t_today",
                    "title": "Danasnji task",
                    "status": "Not Started",
                    "due": today,
                    "priority": "High",
                },
                {
                    "id": "t_tomorrow",
                    "title": "Sutrasnji task",
                    "status": "Not Started",
                    "due": tomorrow,
                    "priority": "Low",
                },
            ],
            "projects": [],
        },
    }


def test_task_question_today_intercepted_and_filtered(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    # Ensure no LLM path is required even if interception fails.
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")

    app = _get_app()
    client = TestClient(app)

    snap = _ready_snapshot_today_and_tomorrow()
    r = client.post(
        "/api/chat",
        json={
            "message": "Da li imamo zadatke za danas?",
            "snapshot": snap,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body.get("read_only") is True
    assert body.get("proposed_commands") == []

    txt = body.get("text") or ""
    # Must be the SSOT task query engine view.
    assert "TASKS (today)" in txt or "tasks (today)" in txt.lower()

    # Must include today task and exclude tomorrow task.
    assert "Danasnji task" in txt
    assert "Sutrasnji task" not in txt
