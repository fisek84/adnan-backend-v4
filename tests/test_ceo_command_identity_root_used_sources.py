from __future__ import annotations

from fastapi.testclient import TestClient

from gateway.gateway_server import app


def test_ceo_command_trace_includes_identity_root_when_lookup_succeeds(
    monkeypatch,
) -> None:
    import routers.ceo_console_router as ceo_console_router  # noqa: PLC0415

    monkeypatch.setattr(
        ceo_console_router,
        "_lookup_identity_id",
        lambda _owner: "11111111-1111-1111-1111-111111111111",
    )

    client = TestClient(app)
    resp = client.post("/api/ceo/command", json={"text": "status (test)"})
    assert resp.status_code == 200

    trace = resp.json().get("trace")
    assert isinstance(trace, dict)
    used = trace.get("used_sources")
    assert isinstance(used, list)

    assert "identity_root" in used

    ctx = resp.json().get("context")
    assert isinstance(ctx, dict)
    ip = ctx.get("identity_pack")
    assert isinstance(ip, dict)
    assert ip.get("identity_id_db") == "11111111-1111-1111-1111-111111111111"


def test_ceo_command_trace_omits_identity_root_when_lookup_returns_none(
    monkeypatch,
) -> None:
    import routers.ceo_console_router as ceo_console_router  # noqa: PLC0415

    monkeypatch.setattr(ceo_console_router, "_lookup_identity_id", lambda _owner: None)

    client = TestClient(app)
    resp = client.post("/api/ceo/command", json={"text": "status (test)"})
    assert resp.status_code == 200

    trace = resp.json().get("trace")
    assert isinstance(trace, dict)
    used = trace.get("used_sources")
    assert isinstance(used, list)

    assert "identity_root" not in used

    ctx = resp.json().get("context")
    assert isinstance(ctx, dict)
    ip = ctx.get("identity_pack")
    assert isinstance(ip, dict)
    # Must be None/absent; never empty string.
    assert ip.get("identity_id_db") is None
