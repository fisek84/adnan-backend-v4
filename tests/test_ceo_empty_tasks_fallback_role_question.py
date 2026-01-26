from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_empty_tasks_fallback_does_not_hijack_role_question(monkeypatch):
    # Keep the test offline/deterministic: do NOT configure LLM.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CEO_ADVISOR_ASSISTANT_ID", raising=False)

    # Snapshot has explicit tasks=[], plus signals (projects/goals).
    # Previously, the phrase "kako mi mozes pomoci" could incorrectly trigger
    # the weekly priorities auto-draft.
    snap = {
        "payload": {
            "tasks": [],
            "projects": [
                {
                    "id": "p1",
                    "title": "Project Alpha",
                    "last_edited_time": "2026-01-01T00:00:00Z",
                }
            ],
            "goals": [
                {
                    "id": "g1",
                    "title": "Goal Beta",
                    "last_edited_time": "2026-01-02T00:00:00Z",
                }
            ],
        }
    }

    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Koja je tvoja uloga u sistemu i kako mi najbolje mozes pomoci?",
            "snapshot": snap,
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    text = data.get("text") or ""
    assert "TASKS snapshot" not in text

    pcs = data.get("proposed_commands") or []
    assert pcs == [] or not any(
        (pc or {}).get("command") == "notion_write" for pc in pcs
    )
