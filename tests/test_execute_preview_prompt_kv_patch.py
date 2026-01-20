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
