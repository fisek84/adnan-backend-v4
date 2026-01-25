from __future__ import annotations

from fastapi.testclient import TestClient

from gateway.gateway_server import app


def test_ceo_command_trace_marks_kb_present() -> None:
    client = TestClient(app)

    resp = client.post(
        "/api/ceo/command",
        json={
            "text": "Daj kratak pregled statusa. (test)",
            "session_id": "test-session-kb-present",
            "source": "pytest",
        },
    )
    assert resp.status_code == 200

    data = resp.json()
    assert isinstance(data, dict)

    trace = data.get("trace")
    assert isinstance(trace, dict)

    used = trace.get("used_sources")
    missing = trace.get("missing_inputs")
    kb_ids_used = trace.get("kb_ids_used")

    assert isinstance(used, list)
    assert isinstance(missing, list)
    assert isinstance(kb_ids_used, list)

    assert "kb" in used
    assert "kb" not in missing
