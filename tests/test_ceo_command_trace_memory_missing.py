from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gateway.gateway_server import app
from services.memory_read_only import ReadOnlyMemoryService


def test_ceo_command_trace_marks_memory_missing_when_snapshot_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(self: ReadOnlyMemoryService):  # type: ignore[no-untyped-def]
        raise RuntimeError("memory backend unavailable")

    monkeypatch.setattr(ReadOnlyMemoryService, "export_public_snapshot", _boom)

    client = TestClient(app)
    resp = client.post(
        "/api/ceo/command",
        json={
            "text": "Provjeri memory missing_inputs (test)",
            "session_id": "test-session-memory-missing",
            "source": "pytest",
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
