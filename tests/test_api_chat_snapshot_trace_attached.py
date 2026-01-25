from fastapi.testclient import TestClient


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def test_api_chat_ceo_advisor_trace_snapshot_payload_and_used_sources():
    app = _get_app()
    client = TestClient(app)

    # Provable bug repro: null lists in snapshot payload must be normalized to []
    # and snapshot must be visible to the agent via grounding_pack + trace.
    r = client.post(
        "/api/chat",
        json={
            "message": "Pokaži projekte i ciljeve iz snapshota.",
            "preferred_agent_id": "ceo_advisor",
            "metadata": {"include_debug": True},
            "snapshot": {"payload": {"goals": None, "tasks": None, "projects": None}},
        },
    )
    assert r.status_code == 200
    body = r.json()

    tr = body.get("trace")
    assert isinstance(tr, dict)

    used = tr.get("used_sources")
    assert isinstance(used, list)
    assert "notion_snapshot" in used

    snap = tr.get("snapshot")
    assert isinstance(snap, dict)
    assert snap.get("ready") in (True, False)

    payload = snap.get("payload")
    assert isinstance(payload, dict)
    assert payload.get("goals") == []
    assert payload.get("tasks") == []
    assert payload.get("projects") == []

    # Prove injection is LLM-visible (grounding pack carries notion_snapshot too).
    gp = body.get("grounding_pack")
    assert isinstance(gp, dict)
    ns = gp.get("notion_snapshot")
    assert isinstance(ns, dict)
    nsp = ns.get("payload")
    assert isinstance(nsp, dict)
    assert isinstance(nsp.get("projects"), list)
