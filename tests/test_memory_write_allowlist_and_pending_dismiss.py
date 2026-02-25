from fastapi.testclient import TestClient

from models.canon import PROPOSAL_WRAPPER_INTENT


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _has_memory_write_proposal(pcs):
    pcs = pcs or []
    if not isinstance(pcs, list):
        return False
    for pc in pcs:
        if not isinstance(pc, dict):
            continue
        if (
            pc.get("command") == PROPOSAL_WRAPPER_INTENT
            and pc.get("intent") == "memory_write"
        ):
            return True
    return False


def test_normal_questions_do_not_trigger_memory_write_proposal():
    app = _load_app()
    client = TestClient(app)

    prompts = [
        "Dali moje stanje ima naziv u medicini i nauci da mogu dalje istrazivati?",
        "U nauci se to zove ...?",
        "Imam problem s memorijom, šta to znači?",
    ]

    for msg in prompts:
        r = client.post(
            "/api/chat",
            json={
                "message": msg,
                "identity_pack": {"user_id": "test"},
                "snapshot": {},
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        pcs = body.get("proposed_commands") or []
        assert not _has_memory_write_proposal(
            pcs
        ), f"unexpected memory_write proposal for: {msg!r}"


def test_valid_memory_write_commands_trigger_proposal():
    app = _load_app()
    client = TestClient(app)

    prompts = [
        "Zapamti ovo: X",
        "Proširi znanje: Y",
        "Remember this: Z",
    ]

    for msg in prompts:
        r = client.post(
            "/api/chat",
            json={
                "message": msg,
                "identity_pack": {"user_id": "test"},
                "snapshot": {},
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        pcs = body.get("proposed_commands") or []
        assert _has_memory_write_proposal(
            pcs
        ), f"expected memory_write proposal for: {msg!r}"


def _setup_pending_proposal_env(monkeypatch, tmp_path, *, state_filename: str):
    # Force deterministic, offline-safe behaviour (no real network IO).
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv("CEO_CONVERSATION_STATE_PATH", str(tmp_path / state_filename))

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)


def test_pending_proposal_dismiss_long_phrase_clears_pending(monkeypatch, tmp_path):
    _setup_pending_proposal_env(
        monkeypatch, tmp_path, state_filename="ceo_conv_state_pending_dismiss_long.json"
    )

    app = _load_app()
    client = TestClient(app)

    session_id = "session_pending_dismiss_long_1"
    snap = {"payload": {"tasks": []}}

    # Step 1: create a pending proposal
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 2 follow-up poruke + 1 email.",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp1.status_code == 200
    pcs1 = resp1.json().get("proposed_commands") or []
    assert isinstance(pcs1, list) and len(pcs1) >= 1

    # Step 2: long dismiss phrase must clear pending state (no confirm-needed loop)
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "nemam namjeru da trazim pamcenje, samo pitanje",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp2.status_code == 200
    tr2 = resp2.json().get("trace") or {}
    assert tr2.get("intent") != "approve_last_proposal_replay"
    assert tr2.get("intent") != "pending_proposal_confirm_needed"

    # Step 3: short yes should NOT replay the old proposal anymore
    resp3 = client.post(
        "/api/chat",
        json={
            "message": "da",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp3.status_code == 200
    tr3 = resp3.json().get("trace") or {}
    assert tr3.get("intent") != "approve_last_proposal_replay"
    pcs3 = resp3.json().get("proposed_commands") or []
    assert pcs3 != pcs1


def test_pending_proposal_cancel_clears_pending(monkeypatch, tmp_path):
    _setup_pending_proposal_env(
        monkeypatch,
        tmp_path,
        state_filename="ceo_conv_state_pending_dismiss_cancel.json",
    )

    app = _load_app()
    client = TestClient(app)

    session_id = "session_pending_dismiss_cancel_1"
    snap = {"payload": {"tasks": []}}

    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 2 follow-up poruke + 1 email.",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp1.status_code == 200
    pcs1 = resp1.json().get("proposed_commands") or []
    assert isinstance(pcs1, list) and len(pcs1) >= 1

    resp2 = client.post(
        "/api/chat",
        json={
            "message": "cancel",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp2.status_code == 200
    tr2 = resp2.json().get("trace") or {}
    assert tr2.get("intent") != "approve_last_proposal_replay"

    resp3 = client.post(
        "/api/chat",
        json={
            "message": "da",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp3.status_code == 200
    tr3 = resp3.json().get("trace") or {}
    assert tr3.get("intent") != "approve_last_proposal_replay"
    pcs3 = resp3.json().get("proposed_commands") or []
    assert pcs3 != pcs1


def test_pending_proposal_yes_still_replays(monkeypatch, tmp_path):
    _setup_pending_proposal_env(
        monkeypatch, tmp_path, state_filename="ceo_conv_state_pending_yes_replay.json"
    )

    app = _load_app()
    client = TestClient(app)

    session_id = "session_pending_yes_replay_1"
    snap = {"payload": {"tasks": []}}

    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 2 follow-up poruke + 1 email.",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp1.status_code == 200
    pcs1 = resp1.json().get("proposed_commands") or []
    assert isinstance(pcs1, list) and len(pcs1) >= 1

    resp2 = client.post(
        "/api/chat",
        json={
            "message": "da",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    tr2 = data2.get("trace") or {}
    assert tr2.get("intent") == "approve_last_proposal_replay"
    pcs2 = data2.get("proposed_commands") or []
    assert pcs2 == pcs1
