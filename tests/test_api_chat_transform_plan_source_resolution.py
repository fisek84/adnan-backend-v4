from __future__ import annotations

from typing import Any, Dict

from fastapi.testclient import TestClient

from models.agent_contract import AgentOutput, ProposedCommand
from services.ceo_conversation_state_store import ConversationStateStore


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _disable_grounding(monkeypatch) -> None:
    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )


def _snapshot_payload() -> Dict[str, Any]:
    return {"payload": {"tasks": [], "goals": [], "projects": []}}


def test_api_chat_transform_this_plan_prefers_last_session_plan_over_embedded_content(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state_transform.json")
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")
    _disable_grounding(monkeypatch)

    app = _load_app()
    client = TestClient(app)

    plan_text = (
        "Evo sedmodnevnog plana za sales onboarding:\n"
        "Dan 1: Audit funnel\n"
        "Dan 2: Definisati ICP\n"
        "Dan 3: Finalizirati ponudu\n"
        "Dan 4: Napisati outreach sekvence\n"
        "Dan 5: Pripremiti CRM pipeline\n"
        "Dan 6: Testirati follow-up poruke\n"
        "Dan 7: Review i iteracija"
    )

    async def _fake_ceo_advisor_agent(_payload, _ctx):  # noqa: ANN001
        return AgentOutput(
            text=plan_text,
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"stub": True},
        )

    captured: Dict[str, Any] = {}

    async def _fake_notion_ops_agent(_payload, ctx=None):  # noqa: ANN001
        captured["message"] = getattr(_payload, "message", "")
        return AgentOutput(
            text="stub notion proposal",
            proposed_commands=[
                ProposedCommand(
                    command="ceo.command.propose",
                    args={"prompt": getattr(_payload, "message", "")},
                    reason="proposal",
                    dry_run=True,
                    requires_approval=True,
                    risk="LOW",
                    scope="api_execute_raw",
                )
            ],
            agent_id="notion_ops",
            read_only=True,
            trace={"stub": True},
        )

    monkeypatch.setattr(
        "routers.chat_router.create_ceo_advisor_agent",
        _fake_ceo_advisor_agent,
        raising=True,
    )
    monkeypatch.setattr(
        "services.notion_ops_agent.notion_ops_agent",
        _fake_notion_ops_agent,
        raising=True,
    )

    session_id = "sess-transform-priority-1"

    r1 = client.post(
        "/api/chat",
        json={
            "message": "Napiši sedmodnevni plan za sales onboarding.",
            "session_id": session_id,
            "snapshot": _snapshot_payload(),
        },
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        "/api/chat",
        json={
            "message": (
                "Pretvori ovaj plan u jedan goal i sedam taskova, poveži taskove sa goalom:\n"
                'Kreiraj centralni cilj "POGRESAN IZVOR".\n'
                "Dan 1: Ovo ne smije biti korišteno"
            ),
            "session_id": session_id,
            "snapshot": _snapshot_payload(),
            "metadata": {"include_debug": True},
        },
    )
    assert r2.status_code == 200, r2.text

    body = r2.json()
    resolved_prompt = captured.get("message") or ""
    assert "Dan 1: Audit funnel" in resolved_prompt
    assert "Dan 7: Review i iteracija" in resolved_prompt
    assert "POGRESAN IZVOR" not in resolved_prompt
    assert "Ovo ne smije biti korišteno" not in resolved_prompt

    pcs = body.get("proposed_commands") or []
    assert isinstance(pcs, list) and len(pcs) == 1
    assert pcs[0].get("args", {}).get("prompt") == resolved_prompt

    trace = body.get("trace") or {}
    pts = trace.get("plan_transform_source") or {}
    assert pts.get("source") == "session_last_relevant"


def test_api_chat_transform_this_plan_uses_embedded_plan_when_session_missing(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_transform_embedded.json"),
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")
    _disable_grounding(monkeypatch)

    app = _load_app()
    client = TestClient(app)

    captured: Dict[str, Any] = {}

    async def _fake_notion_ops_agent(_payload, ctx=None):  # noqa: ANN001
        captured["message"] = getattr(_payload, "message", "")
        return AgentOutput(
            text="stub notion proposal",
            proposed_commands=[
                ProposedCommand(
                    command="ceo.command.propose",
                    args={"prompt": getattr(_payload, "message", "")},
                    reason="proposal",
                    dry_run=True,
                    requires_approval=True,
                    risk="LOW",
                    scope="api_execute_raw",
                )
            ],
            agent_id="notion_ops",
            read_only=True,
            trace={"stub": True},
        )

    monkeypatch.setattr(
        "services.notion_ops_agent.notion_ops_agent",
        _fake_notion_ops_agent,
        raising=True,
    )

    r = client.post(
        "/api/chat",
        json={
            "message": (
                "Pretvori ovaj plan u jedan goal i sedam taskova:\n"
                'Kreiraj centralni cilj "Implementirati KPI OS".\n'
                "Dan 1: KPI plan\n"
                "Dan 2: Mapirati metrike\n"
                "Dan 3: Postaviti dashboard\n"
                "Dan 4: Povezati podatke\n"
                "Dan 5: Testirati izvještaje\n"
                "Dan 6: Refinirati KPI\n"
                "Dan 7: Finalna provjera"
            ),
            "session_id": "sess-transform-embedded-1",
            "snapshot": _snapshot_payload(),
            "metadata": {"include_debug": True},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    resolved_prompt = captured.get("message") or ""
    assert "Implementirati KPI OS" in resolved_prompt
    assert "Dan 7: Finalna provjera" in resolved_prompt

    trace = body.get("trace") or {}
    pts = trace.get("plan_transform_source") or {}
    assert pts.get("source") == "embedded_prompt"


def test_api_chat_transform_this_plan_without_previous_plan_fails_clearly(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_transform_missing.json"),
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")
    _disable_grounding(monkeypatch)

    app = _load_app()
    client = TestClient(app)

    called = {"value": False}

    async def _unexpected_notion_ops_agent(_payload, ctx=None):  # noqa: ANN001
        called["value"] = True
        raise AssertionError("notion_ops_agent should not run without a valid plan source")

    monkeypatch.setattr(
        "services.notion_ops_agent.notion_ops_agent",
        _unexpected_notion_ops_agent,
        raising=True,
    )

    r = client.post(
        "/api/chat",
        json={
            "message": "Pretvori ovaj plan u jedan goal i sedam taskova.",
            "session_id": "sess-transform-missing-1",
            "snapshot": _snapshot_payload(),
            "metadata": {"include_debug": True},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert called["value"] is False
    assert body.get("proposed_commands") == []
    assert "Pošalji plan u istoj poruci" in (body.get("text") or "")

    trace = body.get("trace") or {}
    assert trace.get("intent") == "transform_plan_missing_source"


def test_api_chat_transform_this_plan_does_not_reuse_transform_command_text(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_transform_command_only.json"),
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")
    _disable_grounding(monkeypatch)

    ConversationStateStore.append_turn(
        conversation_id="sess-transform-command-only-1",
        user_text="Pretvori ovaj plan u jedan goal i sedam taskova.",
        assistant_text="Pretvori ovaj plan u jedan goal i sedam taskova.",
    )

    app = _load_app()
    client = TestClient(app)

    called = {"value": False}

    async def _unexpected_notion_ops_agent(_payload, ctx=None):  # noqa: ANN001
        called["value"] = True
        raise AssertionError("command-like history must not be treated as plan content")

    monkeypatch.setattr(
        "services.notion_ops_agent.notion_ops_agent",
        _unexpected_notion_ops_agent,
        raising=True,
    )

    r = client.post(
        "/api/chat",
        json={
            "message": "Pretvori ovaj plan u jedan goal i sedam taskova.",
            "session_id": "sess-transform-command-only-1",
            "snapshot": _snapshot_payload(),
            "metadata": {"include_debug": True},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert called["value"] is False
    assert body.get("proposed_commands") == []
    assert "Pošalji plan u istoj poruci" in (body.get("text") or "")


def test_api_chat_transform_this_plan_does_not_fall_back_to_snapshot_dump(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_transform_snapshot.json"),
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")
    _disable_grounding(monkeypatch)

    app = _load_app()
    client = TestClient(app)

    called = {"value": False}

    async def _unexpected_notion_ops_agent(_payload, ctx=None):  # noqa: ANN001
        called["value"] = True
        raise AssertionError("snapshot dump must not be used as 'ovaj plan' source")

    monkeypatch.setattr(
        "services.notion_ops_agent.notion_ops_agent",
        _unexpected_notion_ops_agent,
        raising=True,
    )

    r = client.post(
        "/api/chat",
        json={
            "message": "Pretvori ovaj plan u jedan goal i sedam taskova.",
            "session_id": "sess-transform-snapshot-1",
            "snapshot": {
                "payload": {
                    "goals": [{"title": "Snapshot Goal"}],
                    "tasks": [
                        {"title": "Snapshot Task 1"},
                        {"title": "Snapshot Task 2"},
                    ],
                    "projects": [],
                }
            },
            "metadata": {"include_debug": True},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert called["value"] is False
    assert body.get("proposed_commands") == []
    assert "Snapshot Goal" not in (body.get("text") or "")
    assert "Snapshot Task 1" not in (body.get("text") or "")

    trace = body.get("trace") or {}
    pts = trace.get("plan_transform_source") or {}
    assert pts.get("snapshot_ignored") is True