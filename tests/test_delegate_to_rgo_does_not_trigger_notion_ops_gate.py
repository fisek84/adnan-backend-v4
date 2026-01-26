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


def test_explicit_delegate_to_rgo_is_read_only_and_no_notion_toggle(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    calls: list[dict] = []

    async def _fake_growth_agent(agent_in, ctx):  # noqa: ANN001
        calls.append({"message": agent_in.message, "ctx": ctx})
        from models.agent_contract import AgentOutput

        payload = {
            "agent": "revenue_growth_operator",
            "task_id": "t_test",
            "objective": agent_in.message,
            "context_ref": {},
            "work_done": [],
            "next_steps": [],
            "recommendations_to_ceo": [],
            "requests_from_ceo": [],
            "notion_ops_proposal": [],
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

    session_id = "session_delegate_rgo_1"
    snap = {"payload": {"tasks": []}}

    resp = client.post(
        "/api/chat",
        json={
            "message": "Pošalji Revenue & Growth Operatoru: napravi mi plan za rast prihoda u narednih 7 dana.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data.get("read_only") is True
    assert data.get("agent_id") == "ceo_advisor"
    pcs = data.get("proposed_commands") or []
    assert pcs == []

    assert len(calls) == 1
    tr = data.get("trace") or {}
    assert tr.get("delegated_to") == "revenue_growth_operator"
    assert tr.get("intent") == "delegate_agent_task"
