from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_ceo_uses_ready_snapshot_when_notion_ops_disarmed(monkeypatch, tmp_path):
    """Regression: Notion snapshot READ must not depend on Notion Ops ARMED.

    We stub the server SSOT snapshot (ready==True) with concrete goal/task titles.
    Then we ask a read question and assert:
    - response text does NOT contain false 'no access / enable snapshot / Notion Ops not active' disclaimers
    - response text contains a concrete string from snapshot payload
    - proposed_commands stays empty
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_snapshot_read.json"),
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    stub_goal_title = "GROWTH: Launch onboarding experiment"

    def _stub_snapshot():
        return {
            "ready": True,
            "status": "fresh",
            "payload": {
                "goals": [{"title": stub_goal_title}],
                "tasks": [{"title": "Task 1"}, {"title": "Task 2"}],
                "projects": [{"title": "Project X"}],
            },
        }

    monkeypatch.setattr(
        KnowledgeSnapshotService, "get_snapshot", staticmethod(_stub_snapshot)
    )

    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Pokaži ciljeve i taskove u Notion.",
            "session_id": "session_snapshot_read_1",
            "snapshot": {},
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert (data.get("proposed_commands") or []) == []

    text = (data.get("text") or "").lower()
    for bad in (
        "nemam pristup",
        "nemam uvid",
        "omogući snapshot",
        "omoguci snapshot",
        "notion ops nije aktiviran",
        "notion ops nije aktivan",
    ):
        assert bad not in text

    assert stub_goal_title.lower() in text
