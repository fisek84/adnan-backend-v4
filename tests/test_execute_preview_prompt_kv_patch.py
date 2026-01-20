from fastapi.testclient import TestClient


# Pokušaj najčešćih entrypoint-a za app
def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_execute_preview_wrapper_applies_prompt_kv_patch_and_title_cutoff():
    app = _load_app()
    client = TestClient(app)

    payload = {
        "command": "ceo.command.propose",
        "intent": "ceo.command.propose",
        "initiator": "ceo_chat",
        "params": {
            "intent_hint": "create_goal",
            "prompt": (
                "Create goal: Grow revenue Q1, Level: 5, Type: Business, Assigned To: Adnan, "
                "Outcome: +10% MRR, Activity State: Active, Status: Active, Priority: High, Deadline: 2026-01-23"
            ),
        },
        "dry_run": True,
        "requires_approval": True,
        "risk": "LOW",
    }

    r = client.post(
        "/api/execute/preview",
        json=payload,
        headers={"X-Initiator": "ceo_chat"},
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert body.get("ok") is True

    cmd = body.get("command") or {}
    assert cmd.get("command") == "notion_write"
    assert cmd.get("intent") == "create_goal"

    params = cmd.get("params") or {}
    # Title should stop before first Key: Value pair.
    assert params.get("title") == "Grow revenue Q1"

    wrapper_patch = params.get("wrapper_patch") or {}
    assert wrapper_patch.get("Level") == "5"
    assert wrapper_patch.get("Type") == "Business"
    assert wrapper_patch.get("Assigned To") == "Adnan"
    assert wrapper_patch.get("Outcome") == "+10% MRR"
    assert wrapper_patch.get("Activity State") == "Active"

    # Validation report is present (warn-only by default).
    notion = body.get("notion") or {}
    validation = notion.get("validation") or {}
    assert isinstance(validation, dict)
    assert validation.get("mode") in {"warn", "strict"}
    assert "summary" in validation


def test_execute_preview_wrapper_create_page_tasks_title_does_not_include_properties():
    app = _load_app()
    client = TestClient(app)

    prompt = (
        "Kreiraj TASK: Ovo je test,\n"
        "Status: Active,\n"
        "Level: goal,\n"
        "Priority: low,\n"
        "Due Date: 23.01.2026,\n"
        "Assigned To: Adnan,\n"
        "Outcome: Unknown,\n"
        "Type: weekly,\n"
        "Activity State: Active,\n"
        "AI Agent: Adnan.Ai,\n"
        "Description: Ovo je test da provjerim da li backend mapira sva polja u Notion properties umjesto u title."
    )

    payload = {
        "command": "ceo.command.propose",
        "intent": "ceo.command.propose",
        "initiator": "ceo_chat",
        "params": {
            "intent_hint": "create_page",
            "db_key": "tasks",
            "prompt": prompt,
        },
        "dry_run": True,
        "requires_approval": True,
        "risk": "LOW",
    }

    r = client.post(
        "/api/execute/preview",
        json=payload,
        headers={"X-Initiator": "ceo_chat"},
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert body.get("ok") is True

    cmd = body.get("command") or {}
    assert cmd.get("command") == "notion_write"
    assert cmd.get("intent") == "create_page"

    params = cmd.get("params") or {}
    assert params.get("db_key") == "tasks"

    ps = params.get("property_specs") or {}
    name_spec = ps.get("Name") or {}
    assert name_spec.get("type") == "title"
    assert name_spec.get("text") == "Ovo je test"

    wrapper_patch = params.get("wrapper_patch") or {}
    assert wrapper_patch.get("Level") == "goal"
    assert wrapper_patch.get("Assigned To") == "Adnan"
    assert wrapper_patch.get("AI Agent") == "Adnan.Ai"

    notion = body.get("notion") or {}
    validation = notion.get("validation") or {}
    assert isinstance(validation, dict)
    assert validation.get("mode") in {"warn", "strict"}
    assert "summary" in validation
