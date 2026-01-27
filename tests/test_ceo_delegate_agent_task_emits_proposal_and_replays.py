from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_delegate_agent_task_emits_proposal_and_replays_on_short_confirm(monkeypatch, tmp_path):
    """Regression (CANON): delegate_agent_task must emit proposed_commands.

    Requirements:
    - Step 1: delegate_agent_task -> proposed_commands.length == 1
    - Step 2: same session + message 'da' -> identical proposed_commands (router replay)
    - LLM/executor must not be called (especially not on replay)

    If proposed_commands is missing/empty, this test MUST fail.
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state_delegate.json")
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(GroundingPackService, "build", lambda **kwargs: {"enabled": False})

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("LLM/executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)

    session_id = "session_delegate_agent_task_1"
    snap = {"payload": {"tasks": []}}

    # Step 1: explicit delegate intent -> must emit proposal
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pošalji agentu revenue_growth_operator: napiši 3 follow-up poruke.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp1.status_code == 200
    data1 = resp1.json()

    pcs1 = data1.get("proposed_commands") or []
    assert isinstance(pcs1, list) and len(pcs1) == 1

    # Step 2: short confirm -> router-level replay of the exact same proposal
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "da",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()

    pcs2 = data2.get("proposed_commands") or []
    assert pcs2 == pcs1

    tr2 = data2.get("trace") or {}
    assert tr2.get("intent") == "approve_last_proposal_replay"
