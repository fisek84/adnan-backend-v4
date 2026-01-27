from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_api_chat_generates_session_id_and_replays_pending_proposal(monkeypatch, tmp_path):
    """Root-cause regression: /api/chat must not rely on cookies for replay.

    Step 1: POST /api/chat WITHOUT session_id -> response returns session_id and a proposal.
    Step 2: POST /api/chat WITH that session_id and message='da' -> identical proposal replayed.

    This test must fail if:
    - session_id is not returned, or
    - replay lookup is not keyed by session_id.
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state_session_id.json")
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(GroundingPackService, "build", lambda **kwargs: {"enabled": False})

    app = _load_app()
    client = TestClient(app)

    snap = {"payload": {"tasks": []}}

    # Step 1: no session_id
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pošalji agentu revenue_growth_operator: napiši 3 follow-up poruke.",
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp1.status_code == 200, resp1.text
    data1 = resp1.json()

    sid = data1.get("session_id")
    assert isinstance(sid, str) and sid.strip()

    pcs1 = data1.get("proposed_commands") or []
    assert isinstance(pcs1, list) and len(pcs1) == 1

    # Step 2: reuse returned session_id
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "da",
            "session_id": sid,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()

    assert (data2.get("session_id") or "") == sid

    pcs2 = data2.get("proposed_commands") or []
    assert pcs2 == pcs1

    tr2 = data2.get("trace") or {}
    assert tr2.get("intent") == "approve_last_proposal_replay"
