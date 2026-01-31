from fastapi.testclient import TestClient


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def _name_text_from_preview(props_preview: dict) -> str:
    name = props_preview.get("Name") or props_preview.get("Project Name") or {}
    title = name.get("title") if isinstance(name, dict) else None
    if isinstance(title, list) and title:
        t0 = title[0]
        if isinstance(t0, dict):
            txt = t0.get("text")
            if isinstance(txt, dict):
                return str(txt.get("content") or "")
    return ""


def test_execute_preview_notion_write_create_goal_prompt_parses_status_priority():
    app = _get_app()
    client = TestClient(app)

    prompt = "Kreiraj cilj: Mjesecni prihod od 5500 BAM, Status active, Priority high"

    payload = {
        "command": "notion_write",
        "intent": "create_goal",
        "params": {
            # even if title is polluted, prompt-first parsing must keep Name clean
            "title": "Mjesecni prihod od 5500 BAM, Status active, Priority high",
            "prompt": prompt,
        },
        "metadata": {"source": "pytest"},
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert body.get("ok") is True

    notion = body.get("notion") or {}
    props_preview = notion.get("properties_preview") or {}
    assert isinstance(props_preview, dict)

    name_text = _name_text_from_preview(props_preview)
    assert name_text == "Mjesecni prihod od 5500 BAM"
    assert "Status active" not in name_text

    status = props_preview.get("Status")
    priority = props_preview.get("Priority")
    assert isinstance(status, dict)
    assert isinstance(priority, dict)

    status_name = (((status.get("select") or {}).get("name")) if "select" in status else ((status.get("status") or {}).get("name")))
    priority_name = ((priority.get("select") or {}).get("name"))

    assert str(status_name or "").strip().lower() == "active"
    assert str(priority_name or "").strip().lower() == "high"

    build = notion.get("build") or {}
    assert isinstance(build, dict)
    assert isinstance(build.get("parsed_props"), dict)
    assert "Status" in build.get("parsed_props")
    assert "Priority" in build.get("parsed_props")


def test_execute_preview_notion_write_prompt_readonly_ignored():
    app = _get_app()
    client = TestClient(app)

    prompt = (
        "Kreiraj cilj: Test goal, "
        "Parent Progress (Rollup): 123, "
        "Activity Lane: X, "
        "Status active"
    )

    payload = {
        "command": "notion_write",
        "intent": "create_goal",
        "params": {
            "title": "Test goal",
            "prompt": prompt,
        },
        "metadata": {"source": "pytest"},
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200, r.text

    body = r.json()
    notion = body.get("notion") or {}
    props_preview = notion.get("properties_preview") or {}
    assert isinstance(props_preview, dict)

    # Must not attempt to write computed/read-only fields
    assert "Parent Progress (Rollup)" not in props_preview
    assert "Activity Lane" not in props_preview

    build = notion.get("build") or {}
    assert isinstance(build, dict)
    ignored = build.get("ignored_readonly_props")
    assert isinstance(ignored, list)
    assert "Parent Progress (Rollup)" in ignored
    assert "Activity Lane" in ignored


def test_execute_preview_notion_write_legacy_title_only_no_prompt_no_parsing():
    app = _get_app()
    client = TestClient(app)

    payload = {
        "command": "notion_write",
        "intent": "create_goal",
        "params": {
            "title": "Legacy title, Status active, Priority high",
        },
        "metadata": {"source": "pytest"},
    }

    r = client.post(
        "/api/execute/preview",
        headers={"X-Initiator": "ceo_chat"},
        json=payload,
    )
    assert r.status_code == 200, r.text

    body = r.json()
    notion = body.get("notion") or {}
    props_preview = notion.get("properties_preview") or {}
    assert isinstance(props_preview, dict)

    # Legacy behavior: only Name from title; no parsing attempted.
    assert _name_text_from_preview(props_preview) == "Legacy title, Status active, Priority high"
    assert "Status" not in props_preview
    assert "Priority" not in props_preview

    # Observability keys should not be present for legacy path.
    build = notion.get("build") or {}
    assert isinstance(build, dict)
    assert build.get("parsed_props") is None
    assert build.get("unknown_props") is None
    assert build.get("ignored_readonly_props") is None
