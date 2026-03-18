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
