import os

from fastapi.testclient import TestClient


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def test_enterprise_preview_editor_flag_off_ignores_patches_in_preview():
    os.environ.pop("ENTERPRISE_PREVIEW_EDITOR", None)
    os.environ.pop("ENTERPRISE_PREVIEW_EDITOR_ENABLED", None)

    app = _get_app()
    client = TestClient(app)

    payload = {
        "command": "notion_write",
        "intent": "batch_request",
        "params": {
            "operations": [
                {
                    "op_id": "goal_1",
                    "intent": "create_goal",
                    "payload": {
                        "title": "Batch Goal",
                        "priority": "High",
                        "status": "Active",
                        "deadline": "2030-02-02",
                    },
                },
            ]
        },
        # Even if a client sends patches, server should behave as legacy when flag is OFF.
        "patches": [{"op_id": "goal_1", "changes": {"Status": "Paused"}}],
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200, r.text

    body = r.json()
    notion = body.get("notion")
    assert isinstance(notion, dict)

    # Enterprise-only field must not appear when flag is OFF.
    assert "canonical_preview_operations" not in notion


def test_enterprise_preview_editor_patches_return_canonical_ops_in_preview():
    os.environ["ENTERPRISE_PREVIEW_EDITOR"] = "1"

    app = _get_app()
    client = TestClient(app)

    payload = {
        "command": "notion_write",
        "intent": "batch_request",
        "params": {
            "operations": [
                {
                    "op_id": "goal_1",
                    "intent": "create_goal",
                    "payload": {
                        "title": "Batch Goal",
                        "priority": "High",
                        "status": "Active",
                        "deadline": "2030-02-02",
                    },
                },
                {
                    "op_id": "task_1",
                    "intent": "create_task",
                    "payload": {
                        "title": "Task 1: Batch Goal",
                        "priority": "Low",
                        "goal_id": "$goal_1",
                    },
                },
            ]
        },
        "patches": [{"op_id": "goal_1", "changes": {"Status": "Paused"}}],
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200, r.text

    body = r.json()
    notion = body.get("notion")
    assert isinstance(notion, dict)

    canonical_ops = notion.get("canonical_preview_operations")
    assert isinstance(canonical_ops, list) and canonical_ops

    goal_ops = [
        op
        for op in canonical_ops
        if isinstance(op, dict) and op.get("op_id") == "goal_1"
    ]
    assert goal_ops

    goal_payload = goal_ops[0].get("payload")
    assert isinstance(goal_payload, dict)

    ps = goal_payload.get("property_specs")
    assert isinstance(ps, dict)

    status = ps.get("Status")
    assert isinstance(status, dict)
    assert status.get("name") == "Paused"

    # Enterprise patched preview forces strict-mode validation.
    v = notion.get("validation")
    assert isinstance(v, dict)
    assert v.get("mode") == "strict"


def test_enterprise_raw_rejects_read_only_patch_fail_closed():
    os.environ["ENTERPRISE_PREVIEW_EDITOR"] = "1"

    app = _get_app()
    client = TestClient(app)

    payload = {
        "command": "notion_write",
        "intent": "batch_request",
        "initiator": "ceo_chat",
        "params": {
            "operations": [
                {
                    "op_id": "goal_1",
                    "intent": "create_goal",
                    "payload": {
                        "title": "Batch Goal",
                        "priority": "High",
                        "status": "Active",
                        "deadline": "2030-02-02",
                    },
                },
            ]
        },
        # 'Activity Lane' is read-only in the offline schema registry for goals.
        "patches": [{"op_id": "goal_1", "changes": {"Activity Lane": "X"}}],
    }

    r = client.post(
        "/api/execute/raw",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 400, r.text

    body = r.json()
    detail = body.get("detail")
    assert isinstance(detail, dict)
    assert detail.get("error") == "validation_failed"

    validation = detail.get("validation")
    assert isinstance(validation, dict)
    assert validation.get("can_approve") is False

    issues = validation.get("issues")
    assert isinstance(issues, list) and issues
    assert any(
        isinstance(it, dict) and it.get("code") == "read_only_field" for it in issues
    ), issues


def test_enterprise_preview_returns_structured_validation_for_invalid_patch():
    os.environ["ENTERPRISE_PREVIEW_EDITOR"] = "1"

    app = _get_app()
    client = TestClient(app)

    payload = {
        "command": "notion_write",
        "intent": "batch_request",
        "params": {
            "operations": [
                {
                    "op_id": "goal_1",
                    "intent": "create_goal",
                    "payload": {
                        "title": "Batch Goal",
                        "priority": "High",
                        "status": "Active",
                        "deadline": "2030-02-02",
                    },
                },
            ]
        },
        # Read-only in offline schema
        "patches": [{"op_id": "goal_1", "changes": {"Activity Lane": "X"}}],
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert body.get("ok") is True

    notion = body.get("notion")
    assert isinstance(notion, dict)
    assert notion.get("type") == "batch_preview"

    v = notion.get("validation")
    assert isinstance(v, dict)
    assert v.get("mode") == "strict"
    assert v.get("can_approve") is False

    # Per-row issues should be surfaced under each row's validation.
    rows = notion.get("rows")
    assert isinstance(rows, list) and rows
    row0 = rows[0]
    rv = row0.get("validation")
    assert isinstance(rv, dict)
    issues = rv.get("issues")
    assert isinstance(issues, list) and issues
    assert any(
        isinstance(it, dict) and it.get("code") == "read_only_field" for it in issues
    ), issues


def test_enterprise_raw_registers_exact_preview_canonical_operations_snapshot():
    os.environ["ENTERPRISE_PREVIEW_EDITOR"] = "1"

    app = _get_app()
    client = TestClient(app)

    proposal = {
        "command": "notion_write",
        "intent": "batch_request",
        "params": {
            "operations": [
                {
                    "op_id": "goal_1",
                    "intent": "create_goal",
                    "payload": {
                        "title": "Batch Goal",
                        "priority": "High",
                        "status": "Active",
                        "deadline": "2030-02-02",
                    },
                },
                {
                    "op_id": "task_1",
                    "intent": "create_task",
                    "payload": {
                        "title": "Task 1: Batch Goal",
                        "priority": "Low",
                        "goal_id": "$goal_1",
                    },
                },
            ]
        },
        "initiator": "ceo_chat",
    }
    patches = [{"op_id": "goal_1", "changes": {"Deadline": "2030-02-03"}}]

    # 1) Preview with patches -> capture canonical operations
    preview_r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json={**proposal, "patches": patches},
    )
    assert preview_r.status_code == 200, preview_r.text
    preview_body = preview_r.json()
    notion = preview_body.get("notion")
    assert isinstance(notion, dict)
    canonical_ops = notion.get("canonical_preview_operations")
    assert isinstance(canonical_ops, list) and canonical_ops

    # 2) Raw with SAME proposal + patches -> must register the exact same operations
    raw_r = client.post(
        "/api/execute/raw",
        headers={"X-Initiator": "ceo_chat"},
        json={**proposal, "patches": patches},
    )
    assert raw_r.status_code == 200, raw_r.text
    raw_body = raw_r.json()

    cmd = raw_body.get("command")
    assert isinstance(cmd, dict)
    params = cmd.get("params")
    assert isinstance(params, dict)
    raw_ops = params.get("operations")
    assert isinstance(raw_ops, list) and raw_ops

    assert raw_ops == canonical_ops
