from fastapi.testclient import TestClient

from models.canon import PROPOSAL_WRAPPER_INTENT


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _trace_intent(body: dict) -> str:
    tr = body.get("trace")
    if isinstance(tr, dict):
        intent = tr.get("intent")
        if isinstance(intent, str):
            return intent
    return ""


def _has_memory_write_proposal(pcs) -> bool:
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


def test_human_memory_does_not_trigger_memory_capability_boilerplate():
    app = _load_app()
    client = TestClient(app)

    msg = (
        "Reci mi sta znas o stanju memorije, kada osoba ne moze da se sjeti broja "
        "... ali kad stavi ruke na tastaturu odmah se sjeti. Sta to govori?"
    )

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
    txt = (body.get("text") or "").casefold()
    intent = _trace_intent(body)

    assert intent != "memory_capability"
    assert "approval-gated" not in txt
    assert "silent write" not in txt
    assert "nema silent" not in txt
    assert "zapamti ovo" not in txt


def test_assistant_memory_question_triggers_memory_capability():
    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Kakvu memoriju koristiš?",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    txt = body.get("text") or ""

    # In this codebase, this phrasing is handled by the deterministic
    # assistant-memory meta-intent (not the legacy memory_capability text).
    assert _trace_intent(body) == "assistant_memory"
    assert "kratkoro" in txt.lower()
    assert "dugoro" in txt.lower()
    assert body.get("proposed_commands") in (None, [])


def test_memory_write_allowlist_still_proposes_approval_gated_write():
    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Zapamti ovo: test",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    pcs = body.get("proposed_commands") or []

    assert _trace_intent(body) != "memory_capability"
    assert _has_memory_write_proposal(pcs)
