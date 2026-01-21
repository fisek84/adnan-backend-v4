import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def _read_text_best_effort(path: Path) -> str:
    data = path.read_bytes()

    # BOM-aware: keep this deterministic across Windows editors.
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")

    # utf-8-sig safely strips UTF-8 BOM if present
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _assert_knowledge_snapshot_contract(ks: dict):
    assert isinstance(ks, dict) and ks, "knowledge_snapshot must be a non-empty object"

    # Enterprise invariants
    assert ks.get("schema_version") == "v1"
    assert ks.get("status") in ("fresh", "stale", "missing_data")
    assert isinstance(ks.get("generated_at"), str) and ks["generated_at"].strip()
    assert isinstance(ks.get("last_sync"), str) and ks["last_sync"].strip()

    payload = ks.get("payload")
    assert isinstance(payload, dict)

    for k in ("goals", "tasks", "projects"):
        assert k in payload
        assert isinstance(payload[k], list)


def test_ceo_console_snapshot_never_empty_kb():
    app = _get_app()
    client = TestClient(app)

    r = client.get("/api/ceo/console/snapshot")
    assert r.status_code == 200

    body = r.json()
    assert isinstance(body.get("knowledge_snapshot"), dict)
    _assert_knowledge_snapshot_contract(body["knowledge_snapshot"])

    sm = body.get("snapshot_meta")
    assert isinstance(sm, dict)
    assert "knowledge_last_sync" in sm
    assert "knowledge_ready" in sm


def test_chat_never_missing_kb_fields():
    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={"message": "Pokaži ciljeve", "snapshot": {}, "metadata": {"initiator": "test"}},
    )
    assert r.status_code == 200

    body = r.json()
    assert body.get("read_only") is True

    assert isinstance(body.get("knowledge_snapshot"), dict)
    _assert_knowledge_snapshot_contract(body["knowledge_snapshot"])

    sm = body.get("snapshot_meta")
    assert isinstance(sm, dict)
    assert "knowledge_status" in sm
    assert "knowledge_generated_at" in sm


def test_ai_run_never_missing_kb_fields():
    app = _get_app()
    client = TestClient(app)

    r = client.post("/api/ai/run", json={"text": "test"})
    assert r.status_code == 200

    body = r.json()
    assert body.get("ok") is True
    assert body.get("read_only") is True

    assert isinstance(body.get("knowledge_snapshot"), dict)
    _assert_knowledge_snapshot_contract(body["knowledge_snapshot"])

    sm = body.get("snapshot_meta")
    assert isinstance(sm, dict)
    assert "knowledge_last_sync" in sm


def test_refresh_snapshot_execute_raw_never_null_result():
    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/execute/raw",
        json={"intent": "refresh_snapshot", "command": "refresh_snapshot", "params": {}},
    )

    # Must not 500/503; even boot-unready must be fail-soft with deterministic result.
    assert r.status_code == 200

    body = r.json()
    assert body.get("read_only") is True
    assert body.get("execution_state") in ("COMPLETED", "FAILED")

    assert body.get("result") is not None
    assert isinstance(body["result"], dict)

    # Deterministic audit fields
    assert "snapshot_meta" in body
    assert isinstance(body.get("snapshot_meta"), dict)


def test_well_known_contract_no_drift_against_runtime():
    root = Path(__file__).resolve().parents[1]
    plugin_path = root / ".well-known" / "ai-plugin.json"
    openapi_path = root / ".well-known" / "openapi.yaml"

    plugin = json.loads(_read_text_best_effort(plugin_path))
    openapi = yaml.safe_load(_read_text_best_effort(openapi_path))

    openapi_paths = set((openapi or {}).get("paths", {}).keys())

    app = _get_app()
    runtime_routes = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if not isinstance(path, str) or not methods:
            continue
        for m in methods:
            runtime_routes.add((path, m.upper()))

    api_routes = (plugin or {}).get("api_routes", {})
    assert isinstance(api_routes, dict) and api_routes

    # plugin -> openapi -> runtime
    for name, spec in api_routes.items():
        assert isinstance(spec, dict), name
        p = spec.get("path")
        m = (spec.get("method") or "").upper()
        assert isinstance(p, str) and p.startswith("/api/"), name
        assert m in ("GET", "POST", "PATCH", "DELETE"), name

        assert p in openapi_paths, f"plugin route missing in openapi: {name} {m} {p}"
        assert (p, m) in runtime_routes, f"plugin route missing in runtime: {name} {m} {p}"

    # Critical UI routes must be present in all three sources.
    critical = {
        ("/api/chat", "POST"),
        ("/api/ai/run", "POST"),
        ("/api/ceo/console/snapshot", "GET"),
        ("/api/execute/raw", "POST"),
        ("/api/execute/preview", "POST"),
    }

    for p, m in critical:
        assert p in openapi_paths
        assert (p, m) in runtime_routes

        found = any(
            isinstance(spec, dict)
            and spec.get("path") == p
            and (spec.get("method") or "").upper() == m
            for spec in api_routes.values()
        )
        assert found, f"critical route missing in ai-plugin.json: {m} {p}"
