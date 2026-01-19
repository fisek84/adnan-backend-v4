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


def test_execute_preview_wrapper_autodetect_intent_builds_table():
    app = _get_app()
    client = TestClient(app)

    # Wrapper without explicit params.intent: should still produce a Notion preview
    payload = {
        "command": "ceo.command.propose",
        "intent": "ceo.command.propose",
        "params": {
            "prompt": "Kreiraj task: Test Task 123",
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
    notion = body.get("notion")
    assert isinstance(notion, dict)
    assert notion.get("db_key") == "tasks"
    pp = notion.get("properties_preview")
    assert isinstance(pp, dict)
    assert "Name" in pp


def test_execute_preview_wrapper_goal_with_explicit_task_list_builds_batch_rows():
    app = _get_app()
    client = TestClient(app)

    payload = {
        "command": "ceo.command.propose",
        "intent": "ceo.command.propose",
        "params": {
            "prompt": (
                'Kreiraj novi cilj pod nazivom "Povećanje prodaje za 20% u Q1 2026." sa rokom do 23.02.2026.\n'
                "Zadaci povezani s ovim ciljem:\n"
                '1. "Analiza tržišta" - due date: 20.01.2026, status: active, priority: low, povezan sa ciljem.\n'
                '2. "Razviti strategiju marketinga" - due date: 20.01.2026, status: active, priority: low, povezan sa ciljem.\n'
            )
        },
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200
    body = r.json()

    notion = body.get("notion")
    assert isinstance(notion, dict)
    assert notion.get("type") == "batch_preview"

    rows = notion.get("rows")
    assert isinstance(rows, list)
    assert len(rows) >= 3

    goal_rows = [
        x for x in rows if isinstance(x, dict) and x.get("intent") == "create_goal"
    ]
    task_rows = [
        x for x in rows if isinstance(x, dict) and x.get("intent") == "create_task"
    ]
    assert goal_rows, rows
    assert task_rows, rows

    # Tasks should reference the created goal by op_id.
    assert any(
        isinstance(x.get("Goal Ref"), str)
        and x.get("Goal Ref", "").startswith("ref:goal_")
        for x in task_rows
    )


def test_execute_preview_wrapper_goal_with_task_colon_list_builds_batch_rows():
    app = _get_app()
    client = TestClient(app)

    payload = {
        "command": "ceo.command.propose",
        "intent": "ceo.command.propose",
        "params": {
            "prompt": (
                'Kreiraj novi cilj pod nazivom "Povećanje prodaje za 20% u Q1 2026." sa rokom do 23.02.2026.\n'
                "Task 1: Analiza tržišta - due date: 20.01.2026, status: active, priority: low.\n"
                "Task 2: Razviti strategiju marketinga - due date: 20.01.2026, status: active, priority: low.\n"
                "Task 3: Implementacija novih prodajnih taktika - due date: 20.01.2026, status: active, priority: low.\n"
            )
        },
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200
    body = r.json()

    notion = body.get("notion")
    assert isinstance(notion, dict)
    assert notion.get("type") == "batch_preview"

    rows = notion.get("rows")
    assert isinstance(rows, list)
    assert len(rows) >= 4

    goal_rows = [
        x for x in rows if isinstance(x, dict) and x.get("intent") == "create_goal"
    ]
    task_rows = [
        x for x in rows if isinstance(x, dict) and x.get("intent") == "create_task"
    ]
    assert goal_rows, rows
    assert task_rows, rows


def test_execute_preview_wrapper_goal_with_single_task_segment_builds_batch_rows():
    app = _get_app()
    client = TestClient(app)

    payload = {
        "command": "ceo.command.propose",
        "intent": "ceo.command.propose",
        "params": {
            "prompt": (
                "Kreiraj novi cilj pod nazivom Povećanje prodaje za 20% u Q1 2026 sa rokom do 23.02.2026. "
                "Task: Analiza tržišta, due date: 20.01.2026, status: active, priority: low, povezan sa ciljem."
            )
        },
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200
    body = r.json()

    notion = body.get("notion")
    assert isinstance(notion, dict)
    assert notion.get("type") == "batch_preview"

    rows = notion.get("rows")
    assert isinstance(rows, list)
    assert len(rows) >= 2

    goal_rows = [
        x for x in rows if isinstance(x, dict) and x.get("intent") == "create_goal"
    ]
    task_rows = [
        x for x in rows if isinstance(x, dict) and x.get("intent") == "create_task"
    ]
    assert goal_rows, rows
    assert task_rows, rows


def test_execute_preview_wrapper_kreiraj_cilj_i_task_lezi_batch_rows():
    app = _get_app()
    client = TestClient(app)

    payload = {
        "command": "ceo.command.propose",
        "intent": "ceo.command.propose",
        "params": {
            "prompt": "Kreiraj cilj: ADNAN X, I TASK LEZI",
            "intent": "create_goal",
        },
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200
    body = r.json()

    notion = body.get("notion")
    assert isinstance(notion, dict)
    assert notion.get("type") == "batch_preview"

    rows = notion.get("rows")
    assert isinstance(rows, list)
    assert len(rows) >= 2

    goal_rows = [
        x for x in rows if isinstance(x, dict) and x.get("intent") == "create_goal"
    ]
    task_rows = [
        x for x in rows if isinstance(x, dict) and x.get("intent") == "create_task"
    ]
    assert goal_rows, rows
    assert task_rows, rows
