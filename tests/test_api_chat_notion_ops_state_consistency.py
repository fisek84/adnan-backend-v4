from __future__ import annotations

from fastapi.testclient import TestClient


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


def _snapshot_payload() -> dict:
    return {"payload": {"tasks": [], "goals": [], "projects": []}}


def test_api_chat_write_like_request_respects_session_armed_state(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_notion_ops_state_consistency.json"),
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _disable_grounding(monkeypatch)

    app = _load_app()
    client = TestClient(app)
    session_id = "ceo-nops-consistency-session-1"

    arm_r = client.post(
        "/api/chat",
        json={
            "message": "notion ops aktiviraj",
            "session_id": session_id,
            "metadata": {"session_id": session_id, "initiator": "ceo_chat"},
        },
    )
    assert arm_r.status_code == 200, arm_r.text

    arm_body = arm_r.json()
    assert arm_body.get("text") == "NOTION OPS: ARMED"
    assert arm_body.get("notion_ops", {}).get("armed") is True

    write_r = client.post(
        "/api/chat",
        json={
            "message": "Kreiraj goal i 3 taska u Notion.",
            "session_id": session_id,
            "snapshot": _snapshot_payload(),
            "metadata": {
                "session_id": session_id,
                "initiator": "ceo_chat",
                "include_debug": True,
            },
        },
    )
    assert write_r.status_code == 200, write_r.text

    body = write_r.json()
    assert body.get("read_only") is True
    assert body.get("agent_id") == "notion_ops"
    assert body.get("notion_ops", {}).get("armed") is True

    text = (body.get("text") or "").lower()
    assert "notion ops nije aktivan" not in text
    assert "not armed" not in text

    proposed_commands = body.get("proposed_commands") or []
    assert isinstance(proposed_commands, list)
    assert len(proposed_commands) >= 1
