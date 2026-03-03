from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def _base_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")


def _snapshot_today_and_tomorrow():
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


def test_today_question_clean_compact_no_meta_no_upcoming(monkeypatch):
    _base_env(monkeypatch)

    app = _get_app()
    client = TestClient(app)
    snap = _snapshot_today_and_tomorrow()

    r = client.post(
        "/api/chat",
        json={"message": "Za danas dali imamo zadatak?", "snapshot": snap},
    )
    assert r.status_code == 200, r.text
    txt = r.json().get("text") or ""

    assert "TASKS (today)" in txt or "tasks (today)" in txt.lower()
    assert "SSOT:" not in txt
    assert "Sljedeća 3" not in txt
    assert "Danasnji task" in txt
    assert "Sutrasnji task" not in txt


def test_today_question_variant_clean_compact(monkeypatch):
    _base_env(monkeypatch)

    app = _get_app()
    client = TestClient(app)
    snap = _snapshot_today_and_tomorrow()

    r = client.post(
        "/api/chat",
        json={"message": "Koje zadatke imamo danas?", "snapshot": snap},
    )
    assert r.status_code == 200, r.text
    txt = r.json().get("text") or ""

    assert "TASKS (today)" in txt or "tasks (today)" in txt.lower()
    assert "SSOT:" not in txt
    assert "Sljedeća 3" not in txt
    assert "Danasnji task" in txt
    assert "Sutrasnji task" not in txt


def test_show_all_tasks_full_mode_paged(monkeypatch):
    _base_env(monkeypatch)

    today = date.today().isoformat()
    tasks = []
    for i in range(1, 31):
        tasks.append(
            {
                "id": f"t{i}",
                "title": f"Task {i}",
                "status": "Not Started",
                "due": today,
                "priority": "-",
            }
        )

    snap = {
        "ready": True,
        "status": "fresh",
        "schema_version": "v1",
        "payload": {"goals": [], "tasks": tasks, "projects": []},
    }

    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Pokazi sve zadatke koje imamo u sistemu",
            "snapshot": snap,
        },
    )
    assert r.status_code == 200, r.text
    txt = r.json().get("text") or ""

    # Clean text: no SSOT meta line.
    assert "SSOT:" not in txt

    # Full mode: must include paging/cap message.
    assert "Prikazano 20 od 30" in txt
    assert "nastavi" in txt.lower()

    # Must include early tasks and exclude later page tasks.
    assert "Task 1" in txt
    assert "Task 20" in txt
    assert "Task 21" not in txt
