from fastapi.testclient import TestClient

from models.canon import PROPOSAL_WRAPPER_INTENT


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _get_memory_public_snapshot(client: TestClient) -> dict:
    r = client.post(
        "/api/chat",
        json={
            "message": "ping",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
            "metadata": {"include_debug": True},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    gp = body.get("grounding_pack")
    assert isinstance(gp, dict)
    ms = gp.get("memory_snapshot")
    assert isinstance(ms, dict)
    payload = ms.get("payload")
    assert isinstance(payload, dict)
    return payload


def test_memory_write_end_to_end_chat_to_approve_to_execute_updates_snapshot():
    app = _load_app()
    client = TestClient(app)

    before = _get_memory_public_snapshot(client)
    before_count = int(before.get("memory_items_count") or 0)
    before_last = before.get("last_memory_write")

    marker = f"e2e memory write marker #{before_count + 1}"

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
    assert "prompt" not in args

    # Create approval via /api/execute/raw
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

    exec_body = exec_r.json()
    approval_id = exec_body.get("approval_id")
    assert isinstance(approval_id, str) and approval_id.strip()

    # Approve (triggers execution)
    approve_r = client.post(
        "/api/ai-ops/approval/approve",
        headers={"X-Initiator": "ceo_chat"},
        json={"approval_id": approval_id, "approved_by": "test"},
    )
    assert approve_r.status_code == 200, approve_r.text

    approve_body = approve_r.json()
    result = approve_body.get("result")
    assert isinstance(result, dict)

    # Must be deterministic success result shape for memory_write
    assert result.get("ok") is True
    assert isinstance(result.get("stored_id"), str) and result.get("stored_id")
    assert isinstance(result.get("memory_count"), int)
    assert isinstance(result.get("last_write"), str) and result.get("last_write")
    assert result.get("errors") == []

    after = _get_memory_public_snapshot(client)
    after_count = int(after.get("memory_items_count") or 0)
    after_last = after.get("last_memory_write")

    assert after_count == before_count + 1
    assert isinstance(after_last, str)
    assert after_last != before_last


def test_memory_write_invalid_payload_is_fail_soft_with_diagnostics():
    app = _load_app()
    client = TestClient(app)

    # Create approval directly for memory_write with invalid grounded_on.
    exec_r = client.post(
        "/api/execute/raw",
        json={
            "command": "memory_write",
            "intent": "memory_write",
            "params": {
                "schema_version": "memory_write.v1",
                "approval_required": True,
                "idempotency_key": "x" * 64,
                "grounded_on": ["KB:memory_model_001"],  # invalid: missing identity ref
                "item": {
                    "type": "fact",
                    "text": "bad payload",
                    "tags": ["t"],
                    "source": "user",
                },
            },
            "payload_summary": {"identity_id": "test_identity"},
            "initiator": "ceo_chat",
        },
    )
    assert exec_r.status_code == 200, exec_r.text
    approval_id = exec_r.json().get("approval_id")
    assert isinstance(approval_id, str) and approval_id.strip()

    approve_r = client.post(
        "/api/ai-ops/approval/approve",
        headers={"X-Initiator": "ceo_chat"},
        json={"approval_id": approval_id, "approved_by": "test"},
    )
    assert approve_r.status_code == 200, approve_r.text
    body = approve_r.json()
    result = body.get("result")
    assert isinstance(result, dict)

    assert result.get("ok") is False
    assert isinstance(result.get("errors"), list) and result.get("errors")
    diag = result.get("diagnostics")
    assert isinstance(diag, dict)
    assert isinstance(diag.get("missing_keys"), list)
    assert "grounded_on" in diag.get("missing_keys")
    assert isinstance(diag.get("recommended_action"), str) and diag.get(
        "recommended_action"
    )
