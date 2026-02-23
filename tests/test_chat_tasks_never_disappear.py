from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from models.agent_contract import AgentOutput


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


def test_post_answer_validator_overrides_contradictory_no_tasks_when_snapshot_has_tasks(
    monkeypatch,
):
    async def _fake_ceo_advisor_agent(agent_input, ctx):  # noqa: ANN001
        return AgentOutput(
            text="U bazi podataka zadataka trenutno nema evidentiranih taskova.",
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"snapshot": {"extracted_tasks_count": 0, "tasks_count": 0}},
        )

    monkeypatch.setattr(
        "routers.chat_router.create_ceo_advisor_agent", _fake_ceo_advisor_agent
    )

    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
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
                    "title": "Prvi task",
                    "fields": {"status": "to do", "due": {"start": "2026-02-21"}},
                },
                {
                    "id": "t2",
                    "title": "Drugi task",
                    "fields": {"status": "in progress", "due": {"start": "2026-02-22"}},
                },
                {
                    "id": "t3",
                    "title": "Treći task",
                    "fields": {"status": "blocked"},
                },
            ],
            "goals": [],
        },
    }

    r = client.post(
        "/api/chat",
        json={
            "message": "Reci mi stanje taskova.",
            "identity_pack": {"user_id": "test"},
            "snapshot": snapshot,
        },
    )
    assert r.status_code == 200, r.text

    txt = str(r.json().get("text") or "")
    t = txt.lower()
    assert "imamo 3 taskova" in t
    assert "prvi task" in t
    assert "nema evidentiranih taskova" not in t


def test_task_query_engine_all_tasks_returns_more_than_top5(monkeypatch):
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
                {"id": "t1", "title": "T1", "fields": {"status": "to do"}},
                {"id": "t2", "title": "T2", "fields": {"status": "to do"}},
                {"id": "t3", "title": "T3", "fields": {"status": "to do"}},
                {"id": "t4", "title": "T4", "fields": {"status": "to do"}},
                {"id": "t5", "title": "T5", "fields": {"status": "to do"}},
                {"id": "t6", "title": "T6", "fields": {"status": "to do"}},
                {"id": "t7", "title": "T7", "fields": {"status": "to do"}},
            ],
            "goals": [],
        },
    }

    r = client.post(
        "/api/chat",
        json={
            "message": "svi taskovi",
            "identity_pack": {"user_id": "test"},
            "snapshot": snapshot,
        },
    )
    assert r.status_code == 200, r.text

    txt = str(r.json().get("text") or "")
    t = txt.lower()
    assert "ssot:" in t
    assert "kontekst=7" in t
    assert "tasks (all)" in t
    for x in ("t1", "t2", "t3", "t4", "t5", "t6", "t7"):
        assert x in t


def test_task_query_engine_today_filters_only_due_today(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")
    monkeypatch.delenv("DEBUG_API_RESPONSES", raising=False)

    app = _load_app()
    client = TestClient(app)

    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    snapshot = {
        "ready": True,
        "payload": {
            "dashboard": {"tasks": []},
            "tasks": [
                {
                    "id": "t1",
                    "title": "Danas 1",
                    "fields": {"status": "to do", "due": {"start": today}},
                },
                {
                    "id": "t2",
                    "title": "Danas 2",
                    "fields": {"status": "in progress", "due": {"start": today}},
                },
                {
                    "id": "t3",
                    "title": "Sutra",
                    "fields": {"status": "to do", "due": {"start": tomorrow}},
                },
            ],
            "goals": [],
        },
    }

    r = client.post(
        "/api/chat",
        json={
            "message": "taskovi za danas",
            "identity_pack": {"user_id": "test"},
            "snapshot": snapshot,
        },
    )
    assert r.status_code == 200, r.text

    txt = str(r.json().get("text") or "")
    t = txt.lower()
    assert "tasks (today)" in t
    assert "danas 1" in t
    assert "danas 2" in t
    assert "sutra" not in t


def test_task_query_engine_overdue_filters_due_before_today_and_not_done(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")
    monkeypatch.delenv("DEBUG_API_RESPONSES", raising=False)

    app = _load_app()
    client = TestClient(app)

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    snapshot = {
        "ready": True,
        "payload": {
            "dashboard": {"tasks": []},
            "tasks": [
                {
                    "id": "t1",
                    "title": "Kasni",
                    "fields": {"status": "to do", "due": {"start": yesterday}},
                },
                {
                    "id": "t2",
                    "title": "Kasni ali gotov",
                    "fields": {"status": "done", "due": {"start": yesterday}},
                },
                {
                    "id": "t3",
                    "title": "Nije kasni",
                    "fields": {"status": "to do", "due": {"start": tomorrow}},
                },
            ],
            "goals": [],
        },
    }

    r = client.post(
        "/api/chat",
        json={
            "message": "overdue taskovi",
            "identity_pack": {"user_id": "test"},
            "snapshot": snapshot,
        },
    )
    assert r.status_code == 200, r.text

    txt = str(r.json().get("text") or "")
    t = txt.lower()
    assert "tasks (overdue)" in t
    assert "kasni" in t
    assert "kasni ali gotov" not in t
    assert "nije kasni" not in t


def test_task_query_engine_by_status_not_started_maps_to_todo(monkeypatch):
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
                {"id": "t1", "title": "Start", "fields": {"status": "to do"}},
                {
                    "id": "t2",
                    "title": "Radi se",
                    "fields": {"status": "in progress"},
                },
            ],
            "goals": [],
        },
    }

    r = client.post(
        "/api/chat",
        json={
            "message": "po statusu: Not Started",
            "identity_pack": {"user_id": "test"},
            "snapshot": snapshot,
        },
    )
    assert r.status_code == 200, r.text

    txt = str(r.json().get("text") or "")
    t = txt.lower()
    assert "tasks (by status)" in t
    assert "start" in t
    assert "radi se" not in t
