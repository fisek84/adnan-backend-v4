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


def test_delegate_to_named_agent_is_read_only_and_no_toggle(monkeypatch, tmp_path):
    """Regression: explicit delegation must never route into notion_ops_toggle UI/approval.

    Even when delegating to the Notion Ops agent, this is an agent-to-agent dispatch
    executed via the existing router and must return read-only output without proposals.
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(GroundingPackService, "build", lambda **kwargs: {"enabled": False})

    calls: list[dict] = []

    async def _fake_notion_ops_agent(agent_in, ctx):  # noqa: ANN001
        calls.append({"message": agent_in.message, "ctx": ctx})
        from models.agent_contract import AgentOutput

        payload = {
            "agent": "notion_ops",
            "ok": True,
            "note": "stubbed notion ops",
            "echo": agent_in.message,
        }

        return AgentOutput(
            text=json.dumps(payload, ensure_ascii=False),
            proposed_commands=[],
            agent_id="notion_ops",
            read_only=True,
            trace={"stub": True},
        )

    monkeypatch.setattr(
        "services.notion_ops_agent.notion_ops_agent",
        _fake_notion_ops_agent,
    )

    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Pošalji agentu Notion Ops: samo objasni trenutno stanje, bez ikakvih write operacija.",
            "session_id": "session_delegate_generic_1",
            "snapshot": {"payload": {"tasks": []}},
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data.get("read_only") is True
    assert data.get("agent_id") == "ceo_advisor"
    assert (data.get("proposed_commands") or []) == []
    assert "notion_ops_toggle" not in json.dumps(data, ensure_ascii=False).lower()

    assert len(calls) == 1
    tr = data.get("trace") or {}
    assert tr.get("intent") == "delegate_agent_task"
    assert tr.get("delegated_to") == "notion_ops"


def test_delegate_unknown_agent_returns_read_only_no_proposals(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(GroundingPackService, "build", lambda **kwargs: {"enabled": False})

    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Pošalji agentu NEPOSTOJI: uradi nešto.",
            "session_id": "session_delegate_generic_2",
            "snapshot": {"payload": {"tasks": []}},
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data.get("read_only") is True
    assert data.get("agent_id") == "ceo_advisor"
    assert (data.get("proposed_commands") or []) == []
    tr = data.get("trace") or {}
    assert tr.get("exit_reason") == "delegate_agent_task.unknown_target"


def test_delegate_missing_target_prompts_agent_picker(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(GroundingPackService, "build", lambda **kwargs: {"enabled": False})

    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Pošalji agentu da mi napiše 3 follow-up poruke.",
            "session_id": "session_delegate_generic_3",
            "snapshot": {"payload": {"tasks": []}},
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data.get("read_only") is True
    assert (data.get("proposed_commands") or []) == []
    txt = data.get("text") or ""
    assert "agent_id" in txt
    assert "revenue_growth_operator" in txt
    tr = data.get("trace") or {}
    assert tr.get("exit_reason") == "delegate_agent_task.missing_target"


def test_delegate_missing_target_with_comma_prompts_picker(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(GroundingPackService, "build", lambda **kwargs: {"enabled": False})

    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Pošalji agentu, napiši 3 follow-up poruke.",
            "session_id": "session_delegate_generic_4",
            "snapshot": {"payload": {"tasks": []}},
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    tr = data.get("trace") or {}
    assert tr.get("exit_reason") == "delegate_agent_task.missing_target"


def test_delegate_to_rgo_without_colon_still_delegates(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(GroundingPackService, "build", lambda **kwargs: {"enabled": False})

    calls: list[dict] = []

    async def _fake_growth_agent(agent_in, ctx):  # noqa: ANN001
        calls.append({"message": agent_in.message, "ctx": ctx})
        from models.agent_contract import AgentOutput

        return AgentOutput(
            text=json.dumps({"agent": "revenue_growth_operator", "echo": agent_in.message}, ensure_ascii=False),
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

    resp = client.post(
        "/api/chat",
        json={
            "message": "Pošalji agentu revenue_growth_operator da mi napiše 3 follow-up poruke.",
            "session_id": "session_delegate_generic_5",
            "snapshot": {"payload": {"tasks": []}},
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (data.get("proposed_commands") or []) == []
    assert len(calls) == 1
    tr = data.get("trace") or {}
    assert tr.get("delegated_to") == "revenue_growth_operator"


def test_delegate_target_before_word_agentu(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(GroundingPackService, "build", lambda **kwargs: {"enabled": False})

    calls: list[dict] = []

    async def _fake_growth_agent(agent_in, ctx):  # noqa: ANN001
        calls.append({"message": agent_in.message, "ctx": ctx})
        from models.agent_contract import AgentOutput

        return AgentOutput(
            text=json.dumps({"agent": "revenue_growth_operator", "echo": agent_in.message}, ensure_ascii=False),
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

    resp = client.post(
        "/api/chat",
        json={
            "message": "Pošalji revenue_growth_operator agentu: napiši 3 follow-up poruke.",
            "session_id": "session_delegate_generic_6",
            "snapshot": {"payload": {"tasks": []}},
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (data.get("proposed_commands") or []) == []
    assert len(calls) == 1
    tr = data.get("trace") or {}
    assert tr.get("delegated_to") == "revenue_growth_operator"
