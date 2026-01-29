from __future__ import annotations

from typing import Any, Dict

from fastapi.testclient import TestClient


def _load_app():
    from gateway.gateway_server import app  # type: ignore

    return app


def test_api_chat_state_question_uses_snapshot_even_when_kb_has_hits(monkeypatch):
    # Force Responses-mode path so build_ceo_instructions() is used.
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")

    # Stub GroundingPackService.build to inject KB hits + Notion snapshot.
    from services.grounding_pack_service import GroundingPackService

    gp = {
        "enabled": True,
        "identity_pack": {"payload": {"system": "test"}},
        "kb_retrieved": {
            "entries": [{"id": "KB1", "title": "T", "content": "C"}],
            "used_entry_ids": ["KB1"],
        },
        "notion_snapshot": {
            "ready": True,
            "payload": {
                "goals": [{"id": "g1"}],
                "tasks": [{"id": "t1"}],
                "projects": [],
            },
        },
        "memory_snapshot": {"payload": {"active_decision": None}},
    }

    monkeypatch.setattr(GroundingPackService, "build", lambda **_k: gp)

    # Stub the executor so no network is used, but the router still exercises the full flow.
    class _Exec:
        async def ceo_command(self, *, text: str, context: Dict[str, Any]) -> Dict[str, Any]:
            return {"text": "Da — imamo ciljeve=1 i taskove=1.", "proposed_commands": []}

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor", lambda **_k: _Exec()
    )

    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Da li imamo ciljeve i taskove u Notion?",
            "session_id": "sess_state_q_1",
            "snapshot": {},
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert (data.get("proposed_commands") or []) == []
    assert data.get("read_only") is True

    txt = (data.get("text") or "").lower()
    assert "trenutno nemam to znanje" not in txt
    assert "nije u kuriranom kb-u" not in txt
