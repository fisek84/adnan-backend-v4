from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_deliverable_confirm_returns_human_report_not_json(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state_presenter.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    async def _fake_growth_agent(agent_in, ctx):  # noqa: ANN001
        from models.agent_contract import AgentOutput

        payload = {
            "agent": "revenue_growth_operator",
            "work_done": [
                {
                    "type": "email_draft",
                    "title": "Email 1",
                    "content": "Email 1: Hello...",
                    "meta": {},
                }
            ],
            "next_steps": ["Pošalji Email 1 i prati odgovore."],
            "recommendations_to_ceo": [],
        }

        return AgentOutput(
            text=json.dumps(payload, ensure_ascii=False),
            proposed_commands=[],
            agent_id="revenue_growth_operator",
            read_only=True,
            trace={"stub": True},
        )

    monkeypatch.setattr(
        "services.revenue_growth_operator_agent.revenue_growth_operator_agent",
        _fake_growth_agent,
    )

    app = _load_app()
    client = TestClient(app)

    session_id = "session_presenter_no_json_1"
    snap = {"payload": {"tasks": []}}

    # Step 1: deliverable request -> proposal (no execution)
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 1 email za cold outreach.",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp1.status_code == 200

    # Step 2: confirm -> real delegation -> CEO-readable report
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "Slažem se, uradi to.",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()

    txt = data2.get("text") or ""
    assert "Izvještaj" in txt
    assert "Email 1" in txt

    # Must not expose raw JSON / technical fields in user-facing text
    assert "{" not in txt
    assert "work_done" not in txt
    assert "meta" not in txt
    assert "agent" not in txt
