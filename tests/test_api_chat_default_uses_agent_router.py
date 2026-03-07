from __future__ import annotations

from fastapi.testclient import TestClient

from models.agent_contract import AgentOutput


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_api_chat_default_path_uses_agent_router(monkeypatch):
    async def _dummy_ceo_advisor_agent(*_args, **_kwargs):
        return AgentOutput(
            text="dummy",
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"dummy": True},
        )

    monkeypatch.setattr(
        "services.ceo_advisor_agent.create_ceo_advisor_agent",
        _dummy_ceo_advisor_agent,
    )

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "hello",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
            "metadata": {"include_debug": True, "read_only": True},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    tr = body.get("trace")
    assert isinstance(tr, dict)

    assert tr.get("router") == "AgentRouterService"
    assert tr.get("selected_agent_id") == "ceo_advisor"
    assert tr.get("selected_by") == "preferred_agent_id"

    ep = tr.get("selected_entrypoint")
    assert isinstance(ep, str)
    assert "services.ceo_advisor_agent:create_ceo_advisor_agent" in ep
