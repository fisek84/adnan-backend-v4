from fastapi.testclient import TestClient

from models.canon import PROPOSAL_WRAPPER_INTENT


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_unknown_mode_kb_miss_does_not_fallback_to_goals_tasks():
    app = _load_app()
    client = TestClient(app)

    payload = {
        "message": "Objasni mi CAP theorem ukratko.",
        "identity_pack": {"user_id": "test"},
        "snapshot": {},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text

    body = r.json()
    txt = body.get("text") or ""

    assert "GOALS (top 3)" not in txt
    assert "TASKS (top 5)" not in txt
    assert "Ne mogu dati smislen odgovor" in txt


def test_memory_capability_answer_is_canonical_and_not_dashboard():
    app = _load_app()
    client = TestClient(app)

    payload = {
        "message": "Možeš li pamtiti stvari između sesija?",
        "identity_pack": {"user_id": "test"},
        "snapshot": {},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text

    body = r.json()
    txt = body.get("text") or ""

    assert "GOALS (top 3)" not in txt
    assert "TASKS (top 5)" not in txt
    assert "[KB:memory_model_001]" in txt


def test_zapamti_ovo_returns_approval_gated_wrapper_even_when_unarmed():
    app = _load_app()
    client = TestClient(app)

    payload = {
        "message": "Zapamti ovo: moj omiljeni KPI je retention.",
        "identity_pack": {"user_id": "test"},
        "snapshot": {},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text

    body = r.json()
    pcs = body.get("proposed_commands") or []
    assert isinstance(pcs, list)
    assert pcs, "expected at least one proposed command"

    first = pcs[0]
    assert isinstance(first, dict)
    assert first.get("command") == PROPOSAL_WRAPPER_INTENT
    assert first.get("requires_approval") is True

    # Canon: wrapper carries an executable memory_write.v1 payload (no prompt).
    assert first.get("intent") == "memory_write"

    args = first.get("args") or {}
    assert isinstance(args, dict)
    assert args.get("schema_version") == "memory_write.v1"
    assert "prompt" not in args
    assert "trace" not in args
    assert args.get("approval_required") is True

    item = args.get("item")
    assert isinstance(item, dict)
    assert isinstance(item.get("text"), str)
    assert "retention" in item.get("text").lower()

    grounded_on = args.get("grounded_on")
    assert isinstance(grounded_on, list)
    assert len(grounded_on) >= 2
    assert "KB:memory_model_001" in grounded_on
    assert "identity_pack.kernel.system_safety" in grounded_on

    idem = args.get("idempotency_key")
    assert isinstance(idem, str) and len(idem) >= 32


def test_disarmed_still_returns_memory_proposal_and_arm_suggestion_when_session_provided():
    app = _load_app()
    client = TestClient(app)

    payload = {
        "message": "Zapamti ovo: disarmed path should still propose memory write.",
        "identity_pack": {"user_id": "test"},
        "snapshot": {},
        "session_id": "test_session_disarmed",
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text

    body = r.json()
    pcs = body.get("proposed_commands") or []
    assert isinstance(pcs, list)
    assert pcs, "expected proposed commands"

    # Must include memory wrapper proposal.
    assert any(
        isinstance(pc, dict)
        and pc.get("command") == PROPOSAL_WRAPPER_INTENT
        and pc.get("intent") == "memory_write"
        for pc in pcs
    )

    # No notion_ops_toggle proposals should be emitted implicitly.
    assert not any(
        isinstance(pc, dict) and pc.get("command") == "notion_ops_toggle" for pc in pcs
    )
