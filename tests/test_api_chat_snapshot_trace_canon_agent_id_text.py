from __future__ import annotations

from fastapi.testclient import TestClient


def test_api_chat_agent_id_text_injects_snapshot_and_trace() -> None:
    from gateway.gateway_server import app  # noqa: PLC0415

    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "agent_id": "ceo_advisor",
            "text": "SNAPSHOT_TRACE",
        },
    )
    assert r.status_code == 200

    body = r.json()
    assert isinstance(body, dict)

    tr = body.get("trace")
    assert isinstance(tr, dict)

    used = tr.get("used_sources")
    assert isinstance(used, list)
    assert "notion_snapshot" in used

    snap = tr.get("snapshot")
    assert isinstance(snap, dict)

    payload = snap.get("payload")
    assert isinstance(payload, dict)

    # Payload must never be null; collections must be lists.
    assert isinstance(payload.get("projects"), list)
    assert isinstance(payload.get("tasks"), list)
    assert isinstance(payload.get("goals"), list)
