from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_chat_is_minimal_by_default(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.delenv("DEBUG_API_RESPONSES", raising=False)

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Koja je naša operativna filozofija?",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert body.get("read_only") is True
    assert isinstance(body.get("text"), str)
    assert isinstance(body.get("proposed_commands"), list)

    # Debug payload must NOT be present by default.
    for k in (
        "knowledge_snapshot",
        "snapshot_meta",
        "grounding_pack",
        "trace_v2",
        "diagnostics",
    ):
        assert k not in body

    # If trace is present, it must be minimal.
    tr = body.get("trace")
    if tr is not None:
        assert isinstance(tr, dict)
        assert set(tr.keys()) <= {"intent"}
        assert isinstance(tr.get("intent"), str)


def test_chat_includes_debug_payload_when_include_debug_true(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.delenv("DEBUG_API_RESPONSES", raising=False)

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Koja je naša operativna filozofija?",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
            "metadata": {"include_debug": True},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert body.get("read_only") is True

    assert isinstance(body.get("knowledge_snapshot"), dict)
    assert isinstance(body.get("snapshot_meta"), dict)

    assert isinstance(body.get("grounding_pack"), dict)
    assert isinstance(body.get("diagnostics"), dict)
    assert isinstance(body.get("trace_v2"), dict)


def test_chat_includes_debug_payload_when_env_enabled(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("DEBUG_API_RESPONSES", "1")

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Koja je naša operativna filozofija?",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()

    assert isinstance(body.get("knowledge_snapshot"), dict)
    assert isinstance(body.get("snapshot_meta"), dict)
    assert isinstance(body.get("grounding_pack"), dict)
    assert isinstance(body.get("diagnostics"), dict)
    assert isinstance(body.get("trace_v2"), dict)
