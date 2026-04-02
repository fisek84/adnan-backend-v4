import importlib
import sys

import pytest
from fastapi import FastAPI


def test_agents_execute_route_not_mounted_on_ssot_app():
    from gateway.gateway_server import app

    paths = [getattr(r, "path", None) for r in getattr(app, "routes", []) or []]
    assert not any(
        isinstance(p, str) and p.startswith("/agents/") for p in paths
    ), "SSOT app must not expose /agents/* routes"


def test_ext_agents_router_import_blocked_in_production(
    monkeypatch: pytest.MonkeyPatch,
):
    # Simulate production context.
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Ensure a clean import so the module-level guard runs.
    sys.modules.pop("ext.agents.router", None)

    with pytest.raises(RuntimeError, match=r"SEC-601"):
        importlib.import_module("ext.agents.router")


def test_boot_time_assertion_fails_in_production_if_agents_route_present(
    monkeypatch: pytest.MonkeyPatch,
):
    from gateway.gateway_server import _sec601_assert_no_agents_routes

    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    app = FastAPI()

    @app.get("/agents/ping")
    def _ping():
        return {"ok": True}

    with pytest.raises(RuntimeError, match=r"SEC-601"):
        _sec601_assert_no_agents_routes(app)
