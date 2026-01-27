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


def test_deliverable_does_not_stick_after_execution(monkeypatch, tmp_path):
    """Regression: pending deliverable proposals only replay on short confirm.

    Scenario:
    1) deliverable request -> proposal
    2) short confirm -> replays same proposal (no execution)
    3) long confirm (contains acknowledgement text) -> must NOT use router replay
    4) new question (contains acknowledgement text) -> must NOT auto-replay
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    calls: list[dict] = []

    async def _fake_growth_agent(agent_in, ctx):  # noqa: ANN001
        calls.append({"message": agent_in.message, "ctx": ctx})
        from models.agent_contract import AgentOutput

        payload = {
            "agent": "revenue_growth_operator",
            "task_id": "t_test",
            "objective": agent_in.message,
            "context_ref": {
                "lead_id": None,
                "account_id": None,
                "meeting_id": None,
                "campaign_id": None,
            },
            "work_done": [
                {
                    "type": "email_draft",
                    "title": "Email 1",
                    "content": "Email 1: Hello...",
                    "meta": {},
                }
            ],
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

    session_id = "session_deliverable_reset_1"
    snap = {"payload": {"tasks": []}}

    # 1) deliverable -> proposal
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 1 follow-up email za lead.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1.get("agent_id") == "ceo_advisor"
    pcs1 = data1.get("proposed_commands") or []
    assert isinstance(pcs1, list) and len(pcs1) >= 1
    assert calls == []

    # 2) short confirm -> replay proposal
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "da",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert calls == [], "Must not delegate/execute in /api/chat"
    pcs2 = data2.get("proposed_commands") or []
    assert pcs2 == pcs1
    tr2 = data2.get("trace") or {}
    assert tr2.get("intent") == "approve_last_proposal_replay"

    # 3) new question (has acknowledgement text) -> must NOT auto-replay
    resp3 = client.post(
        "/api/chat",
        json={
            "message": "Slažem se, uradi to.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp3.status_code == 200
    data3 = resp3.json()

    assert calls == []
    tr3 = data3.get("trace") or {}
    assert str(tr3.get("intent") or "") != "approve_last_proposal_replay"

    # 4) new question (has acknowledgement text) -> must NOT auto-replay
    resp4 = client.post(
        "/api/chat",
        json={
            "message": "Slažem se. Da li pamtiš?",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp4.status_code == 200
    data4 = resp4.json()

    assert calls == []
    pcs4 = data4.get("proposed_commands") or []
    assert pcs4 != pcs1

    tr4 = data4.get("trace") or {}
    assert str(tr4.get("intent") or "") != "approve_last_proposal_replay"
