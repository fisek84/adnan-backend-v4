import asyncio
import os
import uuid

from fastapi.testclient import TestClient

from services.notion_ops_state import set_armed


def _load_app():
    try:
        from gateway.gateway_server import app

        return app
    except (ImportError, ModuleNotFoundError):
        from main import app

        return app


def test_write_intent_generates_proposal_when_not_armed():
    os.environ.pop("OPENAI_API_KEY", None)

    app = _load_app()
    client = TestClient(app)

    session_id = f"test_write_intent_not_armed_{uuid.uuid4().hex}"
    asyncio.run(set_armed(session_id, False, prompt="test"))

    payload = {
        "message": "Kreiraj cilj: ADNAN X, Status: Active, Priority: Low",
        "session_id": session_id,
        "metadata": {"session_id": session_id, "initiator": "ceo_chat"},
    }

    resp = client.post("/api/chat", json=payload)
    assert resp.status_code == 200

    data = resp.json()

    assert data.get("agent_id") == "notion_ops"
    # /api/chat is proposal-only; it must remain read-only.
    assert data.get("read_only") is True
    pcs = data.get("proposed_commands")
    assert isinstance(pcs, list)
    assert len(pcs) > 0
    assert any((pc or {}).get("requires_approval") is True for pc in pcs)
