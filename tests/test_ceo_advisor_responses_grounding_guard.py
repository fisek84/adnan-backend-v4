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


def test_responses_mode_calls_executor_with_non_empty_instructions(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-local")

    # Force grounding_pack to be present
    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: _grounding_pack_full()
    )

    captured: Dict[str, Any] = {}

    class DummyExecutor:
        async def ceo_command(self, text, context):
            captured["instructions"] = (context or {}).get("instructions")
            captured["prompt"] = text
            return {"text": "ok", "proposed_commands": []}

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose: DummyExecutor(),
    )

    app = _load_app()
    client = TestClient(app)
    resp = client.post(
        "/api/chat",
        json={
            "message": "What is AI?",
            "metadata": {"include_debug": True},
            "snapshot": {},
        },
    )
    assert resp.status_code == 200

    instr = captured.get("instructions")
    assert isinstance(instr, str) and instr.strip()
    assert "IDENTITY:" in instr
    assert "KB_CONTEXT:" in instr
    assert "NOTION_SNAPSHOT:" in instr
    assert "MEMORY_CONTEXT:" in instr


def test_responses_mode_blocks_executor_when_grounding_missing(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-local")

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):
        raise AssertionError("executor must not be called when grounding is missing")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)
    resp = client.post(
        "/api/chat",
        json={
            "message": "What is AI?",
            "metadata": {"include_debug": True},
            "snapshot": {},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "Ne mogu dati smislen odgovor" in (data.get("text") or "")
