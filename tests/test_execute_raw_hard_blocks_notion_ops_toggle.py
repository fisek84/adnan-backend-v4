from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_execute_raw_hard_blocks_notion_ops_toggle_creating_approval():
    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/execute/raw",
        json={
            "command": "notion_ops_toggle",
            "intent": "notion_ops_toggle",
            "params": {"session_id": "s1", "armed": True},
            "initiator": "ceo_chat",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body.get("execution_state") == "COMPLETED"
    assert body.get("read_only") is True
    assert body.get("approval_id") is None
    tr = body.get("trace") or {}
    assert isinstance(tr, dict)
    assert tr.get("hard_block_intent") in {"notion_ops_toggle", None}
