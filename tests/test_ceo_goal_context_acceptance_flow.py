from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_ceo_conversation_state(monkeypatch, tmp_path):
    # Deterministic paths persist turns/meta; keep tests hermetic.
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_goal_context_acceptance.json"),
    )


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def _ready_snapshot():
    return {
        "ready": True,
        "status": "fresh",
        "schema_version": "v1",
        "payload": {
            "goals": [
                {
                    "id": "g1",
                    "title": "Rast prihoda Q1",
                    "fields": {"status": "In Progress", "owner": ["ceo@example.com"]},
                },
                {
                    "id": "g2",
                    "title": "Lansiranje novog proizvoda",
                    "fields": {"status": "Not Started", "owner": ["cto@example.com"]},
                },
            ],
            "tasks": [
                {
                    "id": "t1",
                    "title": "Istraživanje tržišta",
                    "fields": {
                        "status": "In Progress",
                        "assigned_to": ["owner1@example.com"],
                        "goal": ["g1"],
                    },
                },
                {
                    "id": "t2",
                    "title": "Priprema prezentacije",
                    "fields": {
                        "status": "Done",
                        "assigned_to": ["owner2@example.com"],
                        "goal": ["g1"],
                    },
                },
                {
                    "id": "t3",
                    "title": "Plan lansiranja",
                    "fields": {
                        "status": "In Progress",
                        "assigned_to": ["owner3@example.com"],
                        "goal": ["g2"],
                    },
                },
            ],
            "projects": [],
        },
    }


def _post_msg(client: TestClient, *, msg: str, conv_id: str, sess_id: str, snap: dict):
    r = client.post(
        "/api/chat",
        json={
            "message": msg,
            "conversation_id": conv_id,
            "session_id": sess_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("read_only") is True
    return body


def test_ceo_goal_context_acceptance_flow_goal_scoped_tasks(monkeypatch):
    """Acceptance flow: goal context persists and task answers remain goal-scoped.

    Flow:
    - Koji je glavni cilj
    - Ko je zadužen za ovaj cilj
    - Imamo li zadatke za ovaj cilj
    - Koji su povezani sa ovim ciljem
    - Da li imamo aktivne zadatke za taj cilj

    Expectations:
    - all task answers are goal-scoped (filtered by goal_id)
    - no global "... u sistemu" Phase A stats
    - no GOALS/TASKS dump output
    """

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")

    app = _get_app()
    client = TestClient(app)

    snap = _ready_snapshot()
    conv_id = "conv-goal-context-acceptance"
    sess_id = "sess-goal-context-acceptance"

    out1 = _post_msg(
        client, msg="Koji je glavni cilj?", conv_id=conv_id, sess_id=sess_id, snap=snap
    )
    t1 = out1.get("text") or ""
    assert "Rast prihoda Q1" in t1

    out2 = _post_msg(
        client,
        msg="Ko je zadužen za ovaj cilj?",
        conv_id=conv_id,
        sess_id=sess_id,
        snap=snap,
    )
    t2 = out2.get("text") or ""
    assert "Rast prihoda Q1" in t2
    assert "ceo@example.com" in t2

    out3 = _post_msg(
        client,
        msg="Imamo li zadatke za ovaj cilj?",
        conv_id=conv_id,
        sess_id=sess_id,
        snap=snap,
    )
    t3 = out3.get("text") or ""
    assert "Rast prihoda Q1" in t3
    assert "u sistemu" not in t3.lower()
    assert "GOALS" not in t3
    assert "TASKS" not in t3

    out4 = _post_msg(
        client,
        msg="Koji su zadaci povezani sa ovim ciljem?",
        conv_id=conv_id,
        sess_id=sess_id,
        snap=snap,
    )
    t4 = out4.get("text") or ""
    assert "Rast prihoda Q1" in t4
    assert "- Istra" in t4 or "Istraživanje" in t4
    assert "Priprema prezentacije" in t4
    # Must not include tasks from other goals.
    assert "Plan lansiranja" not in t4
    assert "u sistemu" not in t4.lower()
    assert "GOALS" not in t4
    assert "TASKS" not in t4

    out5 = _post_msg(
        client,
        msg="Da li imamo aktivne zadatke za taj cilj?",
        conv_id=conv_id,
        sess_id=sess_id,
        snap=snap,
    )
    t5 = out5.get("text") or ""
    assert "Rast prihoda Q1" in t5
    assert "u sistemu" not in t5.lower()
    assert "GOALS" not in t5
    assert "TASKS" not in t5

    # Global guards: none of the answers should look like a snapshot dump.
    all_txt = "\n".join([t1, t2, t3, t4, t5])
    assert "payload" not in all_txt.lower()
    assert "goals (top" not in all_txt.lower()
    assert "tasks (top" not in all_txt.lower()
    assert "Imamo 7 zadataka u sistemu" not in all_txt
