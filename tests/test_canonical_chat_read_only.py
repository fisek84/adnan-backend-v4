from fastapi.testclient import TestClient

from services.approval_state_service import get_approval_state


# Pokušaj najčešćih entrypoint-a za app
def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_api_chat_is_read_only_and_returns_proposals():
    app = _load_app()
    client = TestClient(app)

    payload = {
        "message": "Please create a Notion database schema for weekly KPI tracking (but do not execute).",
        "identity_pack": {"user_id": "test"},
        "snapshot": {"now": "2025-12-25"},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text

    body = r.json()

    # Canonical invariant: endpoint je uvijek READ-ONLY
    assert body["read_only"] is True

    # Struktura odgovora
    assert "agent_id" in body
    assert "proposed_commands" in body
    assert isinstance(body["proposed_commands"], list)

    # Canonical invariant: ako postoje prijedlozi, svi moraju biti dry_run
    for pc in body["proposed_commands"]:
        assert pc.get("dry_run") is True


def test_chat_is_read_only_and_does_not_create_approvals():
    """
    Canon: /api/chat nikad ne smije kreirati approvals.
    Approval lifecycle živi oko /api/execute i sličnih write/ops endpointa,
    ne oko read-only canonical chata.
    """
    app = _load_app()
    client = TestClient(app)

    state = get_approval_state()

    # Snapshot trenutnog stanja approvala
    before = state.list_approvals()
    before_total = len(before)

    payload = {
        "message": "Check my goals and KPIs, but DO NOT execute anything.",
        "identity_pack": {"user_id": "test"},
        "snapshot": {"now": "2025-12-25"},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["read_only"] is True

    # Nakon /api/chat broj approvals mora ostati isti
    after = state.list_approvals()
    after_total = len(after)

    assert after_total == before_total


def test_chat_show_goals_hydrates_snapshot_when_missing(monkeypatch):
    app = _load_app()
    client = TestClient(app)

    # Ensure server-side snapshot hydration is used when client snapshot is empty.
    from services.system_read_executor import SystemReadExecutor

    def _fake_snapshot(self):
        return {
            "ceo_notion_snapshot": {
                "dashboard": {
                    "goals": [
                        {"name": "Goal A", "status": "Active", "priority": "High"}
                    ],
                    "tasks": [],
                }
            }
        }

    monkeypatch.setattr(SystemReadExecutor, "snapshot", _fake_snapshot, raising=True)

    payload = {
        "message": "Pokaži koje ciljeve imamo",
        "identity_pack": {"user_id": "test"},
        "snapshot": {},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["read_only"] is True
    assert "GOALS (top 3)" in (body.get("text") or "")
    assert "Goal A" in (body.get("text") or "")
    assert "Vidim da je stanje prazno" not in (body.get("text") or "")
