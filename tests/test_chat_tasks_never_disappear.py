from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_chat_show_tasks_does_not_claim_empty_when_snapshot_has_tasks(monkeypatch):
    # Keep this test deterministic: show/list requests bypass LLM.
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")
    monkeypatch.delenv("DEBUG_API_RESPONSES", raising=False)

    app = _load_app()
    client = TestClient(app)

    snapshot = {
        "ready": True,
        "payload": {
            "dashboard": {"tasks": []},
            "tasks": [
                {"id": "t1", "title": "T1"},
                {"id": "t2", "title": "T2"},
                {"id": "t3", "title": "T3"},
            ],
            "goals": [],
        },
    }

    r = client.post(
        "/api/chat",
        json={
            "message": "Pokaži zadatke",
            "identity_pack": {"user_id": "test"},
            "snapshot": snapshot,
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    txt = str(body.get("text") or "")
    t = txt.lower()

    # Proof tasks are present in output (not silently dropped).
    assert "tasks (top 5)" in t
    assert "t1" in t
    assert "t2" in t
    assert "t3" in t

    # Safety guard: must not claim "no tasks" when snapshot has tasks.
    assert "nemamo evidentirane nikakve zadatke" not in t
    assert "tasks snapshot je prazan" not in t


def test_chat_task_question_forces_notion_snapshot_in_grounding_used_sources(
    monkeypatch,
):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")
    monkeypatch.delenv("DEBUG_API_RESPONSES", raising=False)

    app = _load_app()
    client = TestClient(app)

    snapshot = {
        "ready": True,
        "payload": {
            "dashboard": {"tasks": []},
            "tasks": [
                {"id": "t1", "title": "T1"},
                {"id": "t2", "title": "T2"},
                {"id": "t3", "title": "T3"},
            ],
            "goals": [],
            "projects": [],
        },
    }

    r = client.post(
        "/api/chat",
        headers={"X-Debug": "1"},
        json={
            "message": "Koje taskove imamo u sistemu?",
            "identity_pack": {"user_id": "test"},
            "snapshot": snapshot,
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    dbg = body.get("debug")
    assert isinstance(dbg, dict)
    audit = dbg.get("audit")
    assert isinstance(audit, dict)

    grounding = audit.get("grounding")
    assert isinstance(grounding, dict)
    used = grounding.get("used_sources")
    assert isinstance(used, list)
    assert "notion_snapshot" in used

    # And with snapshot tasks present, must not claim empty.
    txt = str(body.get("text") or "")
    t = txt.lower()
    assert "tasks (top 5)" in t
    assert "t1" in t
    assert "t2" in t
    assert "t3" in t
    assert "tasks snapshot je prazan" not in t


def test_snapshot_task_fields_are_normalized_in_tasks_block(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")
    monkeypatch.delenv("DEBUG_API_RESPONSES", raising=False)

    app = _load_app()
    client = TestClient(app)

    snapshot = {
        "ready": True,
        "payload": {
            "dashboard": {"tasks": []},
            "tasks": [
                {
                    "id": "t1",
                    "title": "Nazovi klijenta",
                    "fields": {
                        "status": "to do",
                        "due": {"start": "2026-02-21"},
                        "priority": "high",
                    },
                },
                {
                    "id": "t2",
                    "title": "Pošalji ponudu",
                    "fields": {"status": "in progress", "due": {"start": "2026-02-22"}},
                },
                {
                    "id": "t3",
                    "title": "Zatvori sprint",
                    "fields": {"status": "done"},
                },
            ],
            "goals": [],
        },
    }

    r = client.post(
        "/api/chat",
        json={
            "message": "Pokaži zadatke",
            "identity_pack": {"user_id": "test"},
            "snapshot": snapshot,
        },
    )
    assert r.status_code == 200, r.text

    txt = str(r.json().get("text") or "")
    t = txt.lower()
    assert "tasks (top 5)" in t
    assert "nazovi klijenta" in t
    assert "pošalji ponudu" in t
    assert "zatvori sprint" in t

    # Regression: should not render placeholders when tasks exist.
    assert "TASKS (top 5)\n1) - | - | -" not in txt


def test_bosnian_navedi_taskove_lists_titles_and_never_claims_empty(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")
    monkeypatch.delenv("DEBUG_API_RESPONSES", raising=False)

    app = _load_app()
    client = TestClient(app)

    snapshot = {
        "ready": True,
        "payload": {
            "dashboard": {"tasks": []},
            "tasks": [
                {
                    "id": "t1",
                    "title": "Pripremi izvještaj",
                    "fields": {"status": "to do", "due": {"start": "2026-02-23"}},
                },
                {
                    "id": "t2",
                    "title": "Uplati porez",
                    "fields": {"status": "to do"},
                },
                {
                    "id": "t3",
                    "title": "Kontaktiraj dobavljača",
                    "fields": {"status": "blocked"},
                },
            ],
            "goals": [],
        },
    }

    r = client.post(
        "/api/chat",
        json={
            "message": "navedi taskove",
            "identity_pack": {"user_id": "test"},
            "snapshot": snapshot,
        },
    )
    assert r.status_code == 200, r.text

    txt = str(r.json().get("text") or "")
    t = txt.lower()
    assert "tasks (top 5)" in t
    assert "pripremi izvještaj" in t
    assert "uplat" in t
    assert "kontaktiraj dobavljača" in t
    assert "nema navedenih taskova" not in t


def test_snapshot_goal_fields_are_rendered_in_goals_block_no_placeholders(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")
    monkeypatch.delenv("DEBUG_API_RESPONSES", raising=False)

    app = _load_app()
    client = TestClient(app)

    snapshot = {
        "ready": True,
        "payload": {
            "dashboard": {"tasks": [], "goals": []},
            "goals": [
                {
                    "id": "g1",
                    "title": "Povećaj MRR",
                    "fields": {"status": "in progress", "due": {"start": "2026-03-01"}},
                },
                {
                    "id": "g2",
                    "title": "Smanji churn",
                    "fields": {"status": "to do", "due": {"start": "2026-03-15"}},
                },
            ],
            "tasks": [
                {
                    "id": "t1",
                    "title": "Nazovi klijenta",
                    "fields": {"status": "to do", "due": {"start": "2026-02-21"}},
                }
            ],
        },
    }

    r = client.post(
        "/api/chat",
        json={
            "message": "koji su taskovi navedi",
            "identity_pack": {"user_id": "test"},
            "snapshot": snapshot,
        },
    )
    assert r.status_code == 200, r.text

    txt = str(r.json().get("text") or "")
    assert "GOALS (top 3)" in txt

    goals_block = txt.split("TASKS (top 5)")[0]
    g = goals_block.lower()
    assert "povećaj mrr" in g
    assert "smanji churn" in g

    # Only existing goals should be printed (2 goals -> no "3)" line)
    assert "\n3)" not in goals_block

    # No placeholders inside the goals block when goals exist.
    assert "- | - | -" not in goals_block
