from fastapi.testclient import TestClient


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def test_execute_preview_requires_ceo_header():
    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/execute/preview",
        json={"command": "notion_write", "intent": "create_page", "params": {}},
    )
    assert r.status_code == 403


def test_execute_preview_notion_write_shape():
    app = _get_app()
    client = TestClient(app)

    payload = {
        "command": "notion_write",
        "intent": "create_page",
        "params": {
            "db_key": "goals",
            "property_specs": {
                "Name": {"type": "title", "text": "Preview Goal"},
                "Status": {"type": "status", "name": "Active"},
                "Priority": {"type": "select", "name": "Low"},
                "Deadline": {"type": "date", "start": "2030-01-01"},
            },
        },
        "metadata": {"source": "pytest"},
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200

    body = r.json()
    assert body["ok"] is True
    assert body["read_only"] is True

    cmd = body.get("command")
    assert isinstance(cmd, dict)
    assert cmd.get("command") == "notion_write"
    assert cmd.get("intent") == "create_page"

    notion = body.get("notion")
    assert isinstance(notion, dict)
    assert notion.get("db_key") == "goals"

    props_preview = notion.get("properties_preview")
    assert isinstance(props_preview, dict)

    assert "Name" in props_preview
    assert "title" in props_preview["Name"]

    assert props_preview["Status"] == {"status": {"name": "Active"}}
    assert props_preview["Priority"] == {"select": {"name": "Low"}}
    assert props_preview["Deadline"] == {"date": {"start": "2030-01-01"}}


def test_execute_preview_unwraps_ai_command_envelope():
    app = _get_app()
    client = TestClient(app)

    # This mimics the problematic CEO Console proposal where the top-level intent is "notion_write",
    # but the real executable intent is nested under params.ai_command.
    payload = {
        "command": "notion_write",
        "intent": "notion_write",
        "params": {
            "ai_command": {
                "command": "notion_write",
                "intent": "create_page",
                "params": {
                    "db_key": "goals",
                    "property_specs": {
                        "Name": {"type": "title", "text": "Envelope Goal"},
                        "Status": {"type": "status", "name": "Active"},
                    },
                },
            }
        },
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200
    body = r.json()

    cmd = body.get("command")
    assert isinstance(cmd, dict)
    assert cmd.get("command") == "notion_write"
    assert cmd.get("intent") == "create_page"

    notion = body.get("notion")
    assert isinstance(notion, dict)
    assert notion.get("db_key") == "goals"
    assert isinstance(notion.get("properties_preview"), dict)


def test_execute_preview_batch_request_rows():
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
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200
    body = r.json()

    assert body.get("ok") is True
    assert body.get("read_only") is True

    notion = body.get("notion")
    assert isinstance(notion, dict)
    assert notion.get("type") == "batch_preview"

    rows = notion.get("rows")
    assert isinstance(rows, list)
    assert len(rows) >= 2

    r0 = rows[0]
    assert r0.get("op_id") == "goal_1"
    assert r0.get("intent") == "create_goal"
    assert r0.get("db_key") == "goals"
    assert isinstance(r0.get("properties_preview"), dict)
    assert "Name" in r0["properties_preview"]

    r1 = rows[1]
    assert r1.get("op_id") == "task_1"
    assert r1.get("intent") == "create_task"
    assert r1.get("db_key") == "tasks"
    # Relationship reference should be human-readable (from "$goal_1" -> "ref:goal_1")
    assert r1.get("Goal Ref") == "ref:goal_1"
