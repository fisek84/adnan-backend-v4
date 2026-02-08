import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from gateway.gateway_server import app


def _set_required_gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # gateway.gateway_server.validate_runtime_env_or_raise() runs during lifespan boot.
    # In tests, OPENAI_API_KEY is optional, but Notion vars are still required.
    monkeypatch.setenv("NOTION_API_KEY", "test")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test")


def _post_voice_exec(client: TestClient):
    return client.post(
        "/api/voice/exec",
        files={"audio": ("t.wav", b"fake", "audio/wav")},
    )


def test_voice_exec_blocks_write_intent_when_guard_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_required_gateway_env(monkeypatch)
    monkeypatch.setenv("ENABLE_WRITE_INTENT_GUARD", "1")

    with (
        patch(
            "routers.voice_router.voice_service.transcribe",
            new=AsyncMock(return_value="Kreiraj goal Test"),
        ) as m_transcribe,
        patch(
            "routers.voice_router.decision_engine.process_ceo_instruction",
            return_value={
                "operational_output": {
                    "notion_command": {
                        "command": "notion_write",
                        "payload": {"x": 1},
                    }
                }
            },
        ) as m_decision,
        patch(
            "routers.voice_router.agent_router.execute",
            new=AsyncMock(return_value={"agent": "noop", "agent_response": {}}),
        ) as m_execute,
    ):
        with TestClient(app) as client:
            resp = _post_voice_exec(client)

        assert resp.status_code == 200
        data = resp.json()

        # Must block write intents when flag is enabled
        assert data.get("blocked_by") == "write_intent_guard"
        reason = str(data.get("reason") or "")
        assert "write_intent" in reason
        assert data.get("proposal_required") is True or (
            data.get("success") is False and "write_intent" in reason
        )

        # Must not execute when blocked
        assert m_execute.call_count == 0

        # Sanity: upstream mocks were used
        assert m_transcribe.call_count == 1
        assert m_decision.call_count == 1


def test_voice_exec_does_not_block_when_guard_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_required_gateway_env(monkeypatch)
    monkeypatch.setenv("ENABLE_WRITE_INTENT_GUARD", "0")

    with (
        patch(
            "routers.voice_router.voice_service.transcribe",
            new=AsyncMock(return_value="Kreiraj goal Test"),
        ),
        patch(
            "routers.voice_router.decision_engine.process_ceo_instruction",
            return_value={
                "operational_output": {
                    "notion_command": {
                        "command": "notion_write",
                        "payload": {"x": 1},
                    }
                }
            },
        ),
        patch(
            "routers.voice_router.agent_router.execute",
            new=AsyncMock(return_value={"agent": "noop", "agent_response": {}}),
        ) as m_execute,
    ):
        with TestClient(app) as client:
            resp = _post_voice_exec(client)

        assert resp.status_code == 200
        data = resp.json()

        # Default behavior unchanged: guard should not trigger
        assert data.get("blocked_by") != "write_intent_guard"
        assert m_execute.call_count == 1
