from __future__ import annotations

from typing import Any, Dict

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _grounding_pack_full() -> Dict[str, Any]:
    return {
        "enabled": True,
        "identity_pack": {"hash": "h", "payload": {"identity": {"name": "Adnan"}}},
        "kb_retrieved": {
            "used_entry_ids": ["sys_overview_001"],
            "entries": [
                {
                    "id": "sys_overview_001",
                    "title": "Šta je Adnan.AI",
                    "content": "Adnan.AI je ...",
                    "tags": ["system"],
                    "priority": 1.0,
                }
            ],
        },
        "notion_snapshot": {"status": "ok", "last_sync": "2026-01-01"},
        "memory_snapshot": {"hash": "m", "payload": {"notes": ["n1"]}},
    }


def test_conversation_state_is_injected_into_responses_instructions(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: _grounding_pack_full()
    )

    captured: Dict[str, Any] = {}

    class DummyExecutor:
        async def ceo_command(self, text, context):
            captured["instructions"] = (context or {}).get("instructions")
            return {"text": "ok", "proposed_commands": []}

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose: DummyExecutor(),
    )

    app = _load_app()
    client = TestClient(app)

    # Turn 1: deterministic (stores into conversation state)
    r1 = client.post(
        "/api/chat",
        json={
            "message": "Ovo je test kontekst: Fokus mi je Project Alpha.",
            "session_id": "session_conv_1",
            "snapshot": {
                "payload": {
                    "tasks": [],
                    "projects": [{"title": "Project Alpha"}],
                    "goals": [],
                }
            },
        },
    )
    assert r1.status_code == 200

    # Turn 2: normal LLM path; executor called and should see CONVERSATION_STATE
    r2 = client.post(
        "/api/chat",
        json={
            "message": "What is AI?",
            "session_id": "session_conv_1",
            "snapshot": {
                "payload": {"tasks": [{"title": "t1"}], "projects": [], "goals": []}
            },
            "metadata": {"include_debug": True},
        },
    )
    assert r2.status_code == 200

    instr = captured.get("instructions")
    assert isinstance(instr, str) and instr.strip()
    assert "CONVERSATION_STATE:" in instr
