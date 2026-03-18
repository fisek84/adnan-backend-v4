import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from gateway.gateway_server import app
from models.agent_contract import AgentOutput


def _set_required_gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # gateway.gateway_server.validate_runtime_env_or_raise() runs during lifespan.
    # In tests, OPENAI_API_KEY is optional; Notion vars are still required.
    monkeypatch.setenv("NOTION_API_KEY", "test")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test")


def _post_voice_exec(client: TestClient):
    return client.post(
        "/api/voice/exec",
        files={"audio": ("t.wav", b"fake", "audio/wav")},
    )


def test_voice_exec_forwards_to_canonical_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_gateway_env(monkeypatch)

    chat_agent_mock = AsyncMock(
        return_value=AgentOutput(
            text="OK",
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"exit_reason": "stub.voice.forward"},
        )
    )

    with (
        patch(
            "routers.voice_router.voice_service.transcribe",
            new=AsyncMock(return_value="Molim te analiziraj ovaj plan"),
        ) as m_transcribe,
        patch(
            "routers.chat_router.create_ceo_advisor_agent",
            new=chat_agent_mock,
        ),
    ):
        with TestClient(app) as client:
            resp = _post_voice_exec(client)

    assert resp.status_code == 200
    data = resp.json()

    # Voice is STT-only: response is the canonical /api/chat output.
    assert data.get("read_only") is True
    assert data.get("proposed_commands") == []
    assert str(data.get("text") or "") == "OK"

    # Adapter convenience: transcribed text should be present.
    assert data.get("transcribed_text") == "Molim te analiziraj ovaj plan"

    # Ensure we actually went through chat routing.
    assert chat_agent_mock.call_count == 1
    assert m_transcribe.call_count == 1


def test_voice_router_has_no_legacy_decision_or_agent_execute() -> None:
    import routers.voice_router as vr

    assert not hasattr(vr, "decision_engine")
    assert not hasattr(vr, "agent_router")


def test_voice_exec_text_propagates_session_conversation_identity_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_gateway_env(monkeypatch)

    captured = {}

    async def _stub_create_ceo_advisor_agent(payload, ctx):
        captured["payload"] = payload
        captured["ctx"] = ctx
        return AgentOutput(
            text="OK",
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"exit_reason": "stub.voice.ctx"},
        )

    with patch(
        "routers.chat_router.create_ceo_advisor_agent",
        new=AsyncMock(side_effect=_stub_create_ceo_advisor_agent),
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/api/voice/exec_text",
                json={
                    "text": "Pozdrav",
                    "session_id": "s-voice-1",
                    "conversation_id": "c-voice-1",
                    "identity_pack": {"user_id": "u1"},
                },
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("read_only") is True
    assert body.get("proposed_commands") == []
    assert body.get("transcribed_text") == "Pozdrav"
    assert body.get("session_id") == "s-voice-1"

    p = captured.get("payload")
    assert getattr(p, "conversation_id") == "c-voice-1"
    assert getattr(p, "identity_pack").get("user_id") == "u1"
    assert getattr(p, "session_id") == "s-voice-1"

    md = getattr(p, "metadata")
    assert isinstance(md, dict)
    assert md.get("source") == "voice"
    assert md.get("channel") == "voice"
    assert md.get("initiator")

    ctx = captured.get("ctx")
    assert isinstance(ctx, dict)
    assert ctx.get("conversation_id") == "c-voice-1"


def test_voice_exec_text_propagates_x_session_id_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_gateway_env(monkeypatch)

    agent_mock = AsyncMock(
        return_value=AgentOutput(
            text="OK",
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"exit_reason": "stub.voice.header.sid"},
        )
    )

    with patch("routers.chat_router.create_ceo_advisor_agent", new=agent_mock):
        with TestClient(app) as client:
            resp = client.post(
                "/api/voice/exec_text",
                headers={"X-Session-Id": "sid-from-header"},
                json={"text": "Pozdrav"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("session_id") == "sid-from-header"
