from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _arm(session_id: str) -> None:
    from services.notion_ops_state import set_armed

    asyncio.run(set_armed(session_id, True, prompt="test"))


def test_empty_tasks_fallback_generates_priorities_and_proposal_no_executor(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    # Grounding pack can be missing/disabled; fallback must still not call executor.
    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):
        raise AssertionError("executor must not be called in empty-tasks fallback")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    session_id = "session_test_empty_tasks_1"
    _arm(session_id)

    app = _load_app()
    client = TestClient(app)

    snap = {
        "payload": {
            "tasks": [],
            "projects": [
                {
                    "id": "p1",
                    "title": "Project Alpha",
                    "last_edited_time": "2026-01-01T00:00:00Z",
                }
            ],
            "goals": [
                {
                    "id": "g1",
                    "title": "Goal Beta",
                    "last_edited_time": "2026-01-02T00:00:00Z",
                }
            ],
        }
    }

    resp = client.post(
        "/api/chat",
        json={
            "message": "Planiram sljedeću sedmicu — možeš li mi pomoći?",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "TASKS snapshot" in (data.get("text") or "")

    pcs = data.get("proposed_commands") or []
    assert isinstance(pcs, list) and pcs
    pc0 = pcs[0]
    assert pc0.get("command") == "notion_write"

    params = pc0.get("args") or pc0.get("params") or {}
    assert isinstance(params, dict)
    ai_cmd = params.get("ai_command")
    assert isinstance(ai_cmd, dict)
    assert ai_cmd.get("intent") == "batch_request"
    ac_params = ai_cmd.get("params")
    assert isinstance(ac_params, dict)
    ops = ac_params.get("operations")
    assert isinstance(ops, list)
    assert len(ops) == 4  # 1 goal + 3 tasks


def test_empty_tasks_fallback_refuses_without_signals_no_executor(
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
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):
        raise AssertionError("executor must not be called in refusal")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    session_id = "session_test_empty_tasks_2"
    _arm(session_id)

    app = _load_app()
    client = TestClient(app)

    snap = {"payload": {"tasks": [], "projects": [], "goals": []}}

    resp = client.post(
        "/api/chat",
        json={
            "message": "Planiram sljedeću sedmicu — daj prioritete.",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "Nemam dovoljno signala" in (data.get("text") or "")
    pcs = data.get("proposed_commands") or []
    assert pcs == []
