from fastapi.testclient import TestClient


def _get_app():
    """
    Import app lazily so env overrides can be applied in tests if needed.
    Adjust import path if your package layout differs.
    """
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def test_health_is_liveness_and_always_200():
    app = _get_app()
    client = TestClient(app)

    r = client.get("/health")
    assert r.status_code == 200

    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "boot_ready" in body
    assert "boot_error" in body
    assert "ops_safe_mode" in body


def test_ready_is_readiness_and_can_be_503_when_not_ready():
    app = _get_app()
    client = TestClient(app)

    r = client.get("/ready")
    assert r.status_code in (200, 503)

    if r.status_code == 200:
        body = r.json()
        assert body["status"] == "ready"
        assert body["boot_ready"] is True
    else:
        # 503 payload from FastAPI HTTPException is {"detail": "..."}
        body = r.json()
        assert "detail" in body


def test_ceo_console_status_read_only_contract():
    app = _get_app()
    client = TestClient(app)

    r = client.get("/api/ceo-console/status")
    assert r.status_code == 200

    body = r.json()
    assert body["ok"] is True
    assert body["read_only"] is True
    assert body["canon"]["chat_is_read_only"] is True
    assert body["canon"]["no_side_effects"] is True


def test_ai_run_requires_text_and_is_read_only():
    app = _get_app()
    client = TestClient(app)

    # Missing text -> 422 from Pydantic or 400 depending on router validation
    r0 = client.post("/api/ai/run", json={})
    assert r0.status_code in (400, 422)

    r = client.post("/api/ai/run", json={"text": "test"})

    # DEBUG: ako nije 200, ispiši šta backend stvarno vraća
    if r.status_code != 200:
        print("DEBUG /api/ai/run FAILED")
        print("Status code:", r.status_code)
        try:
            print("Response JSON:", r.json())
        except Exception:
            print("Response text:", r.text)

    assert r.status_code == 200

    body = r.json()
    assert body["ok"] is True
    assert body["read_only"] is True
    assert "proposed_commands" in body
    # read-only: proposal wrapper returns proposed_commands list (possibly empty)


def test_ceo_command_legacy_wrapper_is_read_only():
    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/ceo/command",
        json={"input_text": "napravi cilj test cilj, prioritet High, status Active"},
    )
    assert r.status_code == 200

    body = r.json()
    # Response shape from ceo_console_router is typed: ok/read_only/summary/...
    assert body["ok"] is True
    assert body["read_only"] is True
    assert "proposed_commands" in body


def test_ceo_console_snapshot_contains_ssot_payload():
    app = _get_app()
    client = TestClient(app)

    r = client.get("/api/ceo/console/snapshot")
    assert r.status_code == 200

    body = r.json()
    assert "system" in body
    assert "approvals" in body
    assert "knowledge_snapshot" in body

    # SSOT payload (new)
    assert "ceo_dashboard_snapshot" in body
    ssot = body["ceo_dashboard_snapshot"]
    assert isinstance(ssot, dict)

    # legacy keys still present (derived)
    assert "goals_summary" in body
    assert "tasks_summary" in body
    assert isinstance(body["goals_summary"], list)
    assert isinstance(body["tasks_summary"], list)


def test_ceo_command_includes_confidence_risk_block():
    app = _get_app()
    client = TestClient(app)

    r = client.post("/api/ceo/command", json={"input_text": "prikazi stanje"})
    assert r.status_code == 200

    body = r.json()
    assert body["ok"] is True
    assert body["read_only"] is True
    assert "trace" in body
    assert isinstance(body["trace"], dict)

    cr = body["trace"].get("confidence_risk")
    assert isinstance(cr, dict), "trace.confidence_risk missing"

    # required keys
    assert "confidence_score" in cr
    assert "risk_level" in cr
    assert "assumption_count" in cr

    # types + ranges
    assert isinstance(cr["confidence_score"], (int, float))
    assert 0.0 <= float(cr["confidence_score"]) <= 1.0

    assert cr["risk_level"] in ("low", "medium", "high")

    assert isinstance(cr["assumption_count"], int)
    assert cr["assumption_count"] >= 0
