from __future__ import annotations

import json

from fastapi.testclient import TestClient

from models.agent_contract import AgentOutput


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_api_chat_explicit_dept_ops_routes_to_dept_ops_agent(monkeypatch):
    # If routing works, CEO Advisor must not be invoked.
    async def _llm_called(*_args, **_kwargs):
        raise RuntimeError("CEO Advisor called")

    import routers.chat_router as chat_router

    monkeypatch.setattr(chat_router, "create_ceo_advisor_agent", _llm_called, raising=True)

    app = _load_app()
    client = TestClient(app)

    payload = {
        "message": "DEPT OPS: ops.snapshot_health",
        "preferred_agent_id": "dept_ops",
        "metadata": {"include_debug": True},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text

    body = r.json()
    assert body.get("agent_id") == "dept_ops"

    parsed = json.loads(body.get("text") or "")
    assert isinstance(parsed, dict)
    assert parsed.get("kind") == "ops.snapshot_health"

    tr = body.get("trace") or {}
    assert isinstance(tr, dict)
    assert tr.get("dept_ops_strict_backend") is True
    assert tr.get("selected_query") == "ops.snapshot_health"


def test_api_chat_explicit_dept_ops_via_context_hint(monkeypatch):
    async def _llm_called(*_args, **_kwargs):
        raise RuntimeError("CEO Advisor called")

    import routers.chat_router as chat_router

    monkeypatch.setattr(chat_router, "create_ceo_advisor_agent", _llm_called, raising=True)

    app = _load_app()
    client = TestClient(app)

    payload = {
        "message": "ops.snapshot_health",
        "context_hint": {"preferred_agent_id": "dept_ops"},
        "metadata": {"include_debug": True},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text

    body = r.json()
    assert body.get("agent_id") == "dept_ops"

    parsed = json.loads(body.get("text") or "")
    assert isinstance(parsed, dict)
    assert parsed.get("kind") == "ops.snapshot_health"

    tr = body.get("trace") or {}
    assert isinstance(tr, dict)
    assert tr.get("dept_ops_strict_backend") is True
    assert tr.get("selected_query") == "ops.snapshot_health"


def test_api_chat_non_explicit_still_uses_ceo_advisor(monkeypatch):
    calls = {"n": 0}

    async def _stub_advisor(*_args, **_kwargs):
        calls["n"] += 1
        return AgentOutput(
            text="stub-advisor",
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"stubbed": True},
        )

    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router, "create_ceo_advisor_agent", _stub_advisor, raising=True
    )

    app = _load_app()
    client = TestClient(app)

    payload = {
        "message": "hello",
        "metadata": {"include_debug": True},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text

    body = r.json()
    assert calls["n"] == 1
    assert body.get("agent_id") == "ceo_advisor"
    assert (body.get("text") or "").strip() == "stub-advisor"

    tr = body.get("trace") or {}
    assert isinstance(tr, dict)
    assert tr.get("stubbed") is True
