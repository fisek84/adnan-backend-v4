from __future__ import annotations

from fastapi.testclient import TestClient

from models.canon import PROPOSAL_WRAPPER_INTENT


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_memory_snapshot_after_approved_write_is_non_empty():
    """Regression (B): prove SSOT continuity.

    After memory_write is approved+executed, subsequent /api/chat responses must
    expose a non-empty memory snapshot via export_public_snapshot() (no recall
    heuristics/short-circuits).
    """

    app = _load_app()
    client = TestClient(app)

    marker = "frontend continuity marker: FLP 10/10"

    # 1) Ask CEO to remember -> proposal
    chat_r = client.post(
        "/api/chat",
        json={
            "message": f"Zapamti ovo: {marker}",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
            "metadata": {"include_debug": True},
        },
    )
    assert chat_r.status_code == 200, chat_r.text
    chat_body = chat_r.json()
    pcs = chat_body.get("proposed_commands") or []
    assert isinstance(pcs, list) and pcs

    pc = pcs[0]
    assert isinstance(pc, dict)
    assert pc.get("command") == PROPOSAL_WRAPPER_INTENT
    assert pc.get("intent") == "memory_write"
    assert pc.get("requires_approval") is True

    args = pc.get("args")
    assert isinstance(args, dict)
    assert args.get("schema_version") == "memory_write.v1"

    # 2) Create approval via /api/execute/raw
    exec_r = client.post(
        "/api/execute/raw",
        json={
            "command": pc.get("command"),
            "intent": pc.get("intent"),
            "params": args,
            "payload_summary": pc.get("payload_summary") or {},
            "initiator": "ceo_chat",
        },
    )
    assert exec_r.status_code == 200, exec_r.text
    approval_id = exec_r.json().get("approval_id")
    assert isinstance(approval_id, str) and approval_id.strip()

    # 3) Approve (triggers execution)
    approve_r = client.post(
        "/api/ai-ops/approval/approve",
        headers={"X-Initiator": "ceo_chat"},
        json={"approval_id": approval_id, "approved_by": "test"},
    )
    assert approve_r.status_code == 200, approve_r.text
    approve_body = approve_r.json()
    result = approve_body.get("result")
    assert isinstance(result, dict)
    assert result.get("ok") is True

    # 4) Subsequent chat must expose memory snapshot payload
    r2 = client.post(
        "/api/chat",
        json={
            "message": "Ok.",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
            "metadata": {"include_debug": True},
        },
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()

    tr = body.get("trace")
    assert isinstance(tr, dict)
    used = tr.get("used_sources")
    assert isinstance(used, list)
    assert "memory" in used

    gp = body.get("grounding_pack")
    assert isinstance(gp, dict)
    ms = gp.get("memory_snapshot")
    assert isinstance(ms, dict)
    payload = ms.get("payload")
    assert isinstance(payload, dict)

    mic = payload.get("memory_items_count")
    assert isinstance(mic, int)
    assert mic >= 1
