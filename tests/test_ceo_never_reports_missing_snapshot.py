from __future__ import annotations

from fastapi.testclient import TestClient


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def test_ceo_never_reports_missing_snapshot():
    """Regression: CEO Advisor must never claim missing snapshot.

    Invariant (CANON): snapshot is server-owned and injected; user text must not
    mention internal terms like 'snapshot' nor use 'nemam*' phrasing.
    """

    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Koje zadatke imam sutra?",
            "snapshot": {},
            "metadata": {"initiator": "test"},
        },
    )
    assert r.status_code == 200

    body = r.json()
    txt = (body.get("text") or "").strip()
    low = txt.lower()

    assert "snapshot" not in low
    assert "nemam" not in low
