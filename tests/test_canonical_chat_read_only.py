from fastapi.testclient import TestClient


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
