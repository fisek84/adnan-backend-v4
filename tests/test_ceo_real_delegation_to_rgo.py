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


def test_deliverable_proposal_then_confirm_executes_rgo_no_notion(
    monkeypatch, tmp_path
):
    """Real delegation: CEO proposal -> user confirm -> actual RGO call.

    Requirements:
    - No LLM/executor usage (mock)
    - Confirm step calls revenue_growth_operator_agent via existing router
    - Output contains real RGO content (not meta)
    - trace includes delegated_to + delegation_reason
    - deliverable flow emits no Notion proposals/toggles
    - tasks=[] must not hijack into weekly/kickoff
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")

    # Grounding pack can be missing/disabled; deliverable proposal/confirm must still work.
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
                },
                {
                    "type": "email_draft",
                    "title": "Email 2",
                    "content": "Email 2: Hi...",
                    "meta": {},
                },
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

    session_id = "session_real_delegation_1"

    snap = {"payload": {"tasks": []}}

    # Step 1: deliverable request -> proposal (no real execution yet)
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 3 follow-up poruke + 2 emaila za leadove.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp1.status_code == 200
    data1 = resp1.json()

    assert data1.get("agent_id") == "ceo_advisor"
    assert (data1.get("proposed_commands") or []) == []
    assert "notion" not in (data1.get("text") or "").lower()
    assert (
        "uradi" in (data1.get("text") or "").lower()
        or "proceed" in (data1.get("text") or "").lower()
    )
    assert calls == [], "RGO must not be called before confirmation"

    # Step 2: user confirms -> real delegation + real output
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "Slažem se, uradi to.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()

    assert len(calls) == 1, "Expected exactly one real RGO call"
    assert calls[0]["message"].startswith("Pripremi 3 follow-up")

    txt2 = data2.get("text") or ""
    assert "Email 1" in txt2 and "Email 2" in txt2
    assert "pripremio sam json" not in txt2.lower()

    # No Notion proposals/toggles in deliverable confirm output
    pcs2 = data2.get("proposed_commands") or []
    assert pcs2 == []

    tr2 = data2.get("trace") or {}
    assert tr2.get("delegated_to") == "revenue_growth_operator"
    assert "deliverable" in str(tr2.get("delegation_reason") or "").lower()


def test_weekly_explicit_does_not_call_rgo(monkeypatch, tmp_path):
    """Weekly explicit routes to CEO weekly flow, not RGO."""

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

    calls: list[int] = []

    async def _fake_growth_agent(_agent_in, _ctx):  # noqa: ANN001
        calls.append(1)
        from models.agent_contract import AgentOutput

        return AgentOutput(
            text=json.dumps({"agent": "revenue_growth_operator"}, ensure_ascii=False),
            proposed_commands=[],
            agent_id="revenue_growth_operator",
            read_only=True,
            trace={"stub": True},
        )

    monkeypatch.setattr(
        "services.revenue_growth_operator_agent.revenue_growth_operator_agent",
        _fake_growth_agent,
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Daj mi sedmične prioritete i sedmični plan.",
            "session_id": "session_weekly_no_rgo_1",
            "snapshot": {
                "payload": {
                    "tasks": [],
                    "projects": [{"id": "p1", "title": "P"}],
                    "goals": [{"id": "g1", "title": "G"}],
                }
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("agent_id") == "ceo_advisor"
    assert calls == []

    txt = data.get("text") or ""
    assert "TASKS snapshot" in txt
