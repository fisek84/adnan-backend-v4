from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gateway.gateway_server import app
from services.memory_read_only import ReadOnlyMemoryService


def test_api_chat_trace_marks_memory_missing_when_snapshot_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(self: ReadOnlyMemoryService):  # type: ignore[no-untyped-def]
        raise RuntimeError("memory backend unavailable")

    monkeypatch.setattr(ReadOnlyMemoryService, "export_public_snapshot", _boom)

    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Test memory missing trace",
            "session_id": "test-api-chat-memory-missing",
            "snapshot": {"payload": {"tasks": []}},
            "metadata": {"include_debug": True},
        },
    )
    assert resp.status_code == 200

    data = resp.json()
    assert isinstance(data, dict)

    trace = data.get("trace")
    assert isinstance(trace, dict)

    missing = trace.get("missing_inputs")
    assert isinstance(missing, list)
    assert "memory" in missing

    # DEBUG-only memory diagnostics are allowed; assert presence when debug enabled.
    assert trace.get("memory_provider") == "readonly_memory_service"
    assert "memory_items_count" in trace
    assert isinstance(trace.get("memory_items_count"), int)
    assert "memory_error" in trace
    assert trace.get("memory_error") is None or isinstance(trace.get("memory_error"), str)
