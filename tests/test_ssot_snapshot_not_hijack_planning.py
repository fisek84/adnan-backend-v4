from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_planning_discussion_first_does_not_return_ssot_snapshot_template(
    monkeypatch, tmp_path
):
    """Regression: planning/discussion prompts must not short-circuit into SSOT snapshot_read_summary."""

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_planning_discuss_first.json"),
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(GroundingPackService, "build", lambda **_k: {"enabled": False})

    from services.knowledge_snapshot_service import KnowledgeSnapshotService

    def _stub_snapshot():
        return {
            "ready": True,
            "status": "fresh",
            "payload": {
                "goals": [{"title": "ADNAN X"}],
                "tasks": [],
                "projects": [],
            },
        }

    monkeypatch.setattr(
        KnowledgeSnapshotService, "get_snapshot", staticmethod(_stub_snapshot)
    )

    def _boom(*_a, **_k):
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)

    msg = (
        "Imam cilj… treba mi pomoć da postavim cilj/podcilj/taskove u Notion. "
        "Neću sad da postavljam nego želim da prvo razgovaramo."
    )

    resp = client.post(
        "/api/chat",
        json={
            "message": msg,
            "session_id": "session_planning_discuss_first_1",
            "snapshot": {},
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    text = data.get("text") or ""
    assert "Imam SSOT Notion snapshot (READ):" not in text

    tr = data.get("trace") or {}
    assert tr.get("intent") != "snapshot_read_summary"


def test_explicit_snapshot_request_still_returns_structured_snapshot(monkeypatch):
    """Regression: explicit snapshot/show requests must still return snapshot output."""

    from services.system_read_executor import SystemReadExecutor

    def _fake_snapshot(self):
        return {
            "ceo_notion_snapshot": {
                "dashboard": {
                    "goals": [
                        {"name": "Goal A", "status": "Active", "priority": "High"}
                    ],
                    "tasks": [
                        {"title": "Task 1", "status": "To Do", "priority": "High"}
                    ],
                }
            }
        }

    monkeypatch.setattr(SystemReadExecutor, "snapshot", _fake_snapshot, raising=True)

    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Pokaži snapshot ciljeva i taskova",
            "session_id": "session_show_snapshot_1",
            "snapshot": {},
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "GOALS (top 3)" in (body.get("text") or "")
    assert "TASKS (top 5)" in (body.get("text") or "")


def test_notio_ops_activation_path_unchanged(tmp_path, monkeypatch):
    """Regression: Notion Ops activation via chat keywords remains unchanged."""

    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT", "false")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state_ops_act.json")
    )

    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "notion ops aktiviraj",
            "session_id": "session_ops_activate_1",
            "metadata": {"session_id": "session_ops_activate_1", "initiator": "ceo_chat"},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data.get("notion_ops"), dict)
    assert data["notion_ops"]["armed"] is True
