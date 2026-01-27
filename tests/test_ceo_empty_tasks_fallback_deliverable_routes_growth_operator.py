from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _arm(session_id: str) -> None:
    from services.notion_ops_state import set_armed

    asyncio.run(set_armed(session_id, True, prompt="test"))


def test_empty_tasks_fallback_does_not_hijack_deliverable_intent(monkeypatch, tmp_path):
    """Regression: deliverable drafting must route to revenue_growth_operator.

    Scenario:
    - snapshot.payload.tasks is present but empty
    - prompt asks for concrete outreach deliverables (follow-up poruke)

    Expect:
    - step 1 returns CEO proposal (no execution)
    - step 2 confirmation replays the same proposal (no execution)
    - response text does NOT contain the empty-tasks weekly priorities header
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    calls: list[dict] = []

    async def _fake_growth_agent(agent_in, ctx):  # noqa: ANN001
        calls.append({"message": agent_in.message, "ctx": ctx})
        from models.agent_contract import AgentOutput

        payload = {
            "agent": "revenue_growth_operator",
            "task_id": "t_test",
            "objective": "draft follow-up",
            "context_ref": {
                "lead_id": None,
                "account_id": None,
                "meeting_id": None,
                "campaign_id": None,
            },
            "work_done": [
                {
                    "type": "outreach_sequence",
                    "title": "Follow-up sequence",
                    "content": "1) ...\n2) ...",
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

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    session_id = "session_test_empty_tasks_deliverable_1"
    _arm(session_id)

    app = _load_app()
    client = TestClient(app)

    snap = {"payload": {"tasks": [], "projects": [], "goals": []}}

    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pomozi mi pripremiti follow-up poruke za leadove (2 varijante).",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1.get("agent_id") == "ceo_advisor"

    txt1 = data1.get("text") or ""
    assert "TASKS snapshot is empty" not in txt1
    assert "weekly" not in txt1.lower()
    pcs1 = data1.get("proposed_commands") or []
    assert isinstance(pcs1, list) and len(pcs1) >= 1
    assert calls == []

    resp2 = client.post(
        "/api/chat",
        json={
            "message": "Uradi to.",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()

    txt2 = data2.get("text") or ""
    assert "TASKS snapshot is empty" not in txt2
    assert "weekly" not in txt2.lower()

    pcs2 = data2.get("proposed_commands") or []
    assert pcs2 == pcs1
    assert calls == []

    # Must not leak raw RGO JSON.
    assert "{" not in txt2
    assert "work_done" not in txt2
    assert "meta" not in txt2
    assert "agent" not in txt2
