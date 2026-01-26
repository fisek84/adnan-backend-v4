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
    - step 1 returns CEO proposal (no execution yet)
    - step 2 confirmation triggers a real RGO call
    - response text does NOT contain the empty-tasks weekly priorities header
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    async def _fake_growth_agent(_agent_in, _ctx):  # noqa: ANN001
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
    assert (data1.get("proposed_commands") or []) == []

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

    # Sanity: the embedded payload should still contain RGO JSON.
    i0 = txt2.find("{")
    assert i0 >= 0
    parsed = json.loads(txt2[i0:])
    assert parsed.get("agent") == "revenue_growth_operator"
