from __future__ import annotations

from fastapi.testclient import TestClient

from gateway.gateway_server import app


def test_ceo_console_command_debug_includes_memory_trace_fields() -> None:
    client = TestClient(app)

    resp = client.post(
        "/api/ceo-console/command",
        json={
            "text": "Debug memory trace fields (test)",
            "session_id": "test-ceo-console-debug-memory-trace",
            "context_hint": {"include_debug": True},
        },
    )
    assert resp.status_code == 200

    data = resp.json()
    assert isinstance(data, dict)

    trace = data.get("trace")
    assert isinstance(trace, dict)

    assert trace.get("memory_provider") == "readonly_memory_service"
    assert "memory_items_count" in trace
    assert isinstance(trace.get("memory_items_count"), int)

    # May be None or a string depending on backend availability.
    assert "memory_error" in trace
    assert trace.get("memory_error") is None or isinstance(
        trace.get("memory_error"), str
    )
