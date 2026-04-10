import os

import pytest
from starlette.testclient import TestClient

from tests.auth_utils import auth_headers


def _isolate_notion_armed_store(monkeypatch, tmp_path):
    # Avoid generating repo artifacts (data/notion_armed_store.json) during tests.
    monkeypatch.setenv(
        "NOTION_ARMED_STORE_PATH", str(tmp_path / "notion_armed_store.json")
    )


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _refresh_snapshot_payload(*, session_id: str):
    # Keep payload intentionally minimal; we only need principal resolution and a 200.
    return {
        "command": "refresh_snapshot",
        "intent": "refresh_snapshot",
        "params": {},
        "session_id": session_id,
        "metadata": {"session_id": session_id},
    }


def test_enforced_browser_session_execute_raw_accepts_valid_token(
    monkeypatch, tmp_path
):
    _isolate_notion_armed_store(monkeypatch, tmp_path)
    app = _load_app()

    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT", "true")
    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT_TESTS", "true")
    monkeypatch.setenv("CEO_APPROVAL_TOKEN", "test_secret_123")

    session_id = "p0-enforced-browser-session-1"

    with TestClient(app) as client:
        r = client.post(
            "/api/execute/raw",
            headers={
                "X-Initiator": "ceo_chat",
                "X-CEO-Token": "test_secret_123",
            },
            json=_refresh_snapshot_payload(session_id=session_id),
        )

    assert r.status_code == 200, r.text


def test_enforced_browser_session_execute_raw_rejects_spoof_only_initiator(
    monkeypatch, tmp_path
):
    _isolate_notion_armed_store(monkeypatch, tmp_path)
    app = _load_app()

    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT", "true")
    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT_TESTS", "true")
    monkeypatch.setenv("CEO_APPROVAL_TOKEN", "test_secret_123")

    session_id = "p0-enforced-browser-session-2"

    with TestClient(app) as client:
        r = client.post(
            "/api/execute/raw",
            headers={
                "X-Initiator": "ceo_chat",
            },
            json=_refresh_snapshot_payload(session_id=session_id),
        )

    assert r.status_code == 403, r.text


def test_enforced_browser_session_execute_raw_rejects_wrong_token(
    monkeypatch, tmp_path
):
    _isolate_notion_armed_store(monkeypatch, tmp_path)
    app = _load_app()

    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT", "true")
    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT_TESTS", "true")
    monkeypatch.setenv("CEO_APPROVAL_TOKEN", "test_secret_123")

    session_id = "p0-enforced-browser-session-3"

    with TestClient(app) as client:
        r = client.post(
            "/api/execute/raw",
            headers={
                "X-Initiator": "ceo_chat",
                "X-CEO-Token": "wrong_token",
            },
            json=_refresh_snapshot_payload(session_id=session_id),
        )

    assert r.status_code == 403, r.text


def test_enforced_browser_session_approve_rejects_spoof_only_initiator(
    monkeypatch, tmp_path
):
    _isolate_notion_armed_store(monkeypatch, tmp_path)
    app = _load_app()

    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT", "true")
    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT_TESTS", "true")
    monkeypatch.setenv("CEO_APPROVAL_TOKEN", "test_secret_123")

    with TestClient(app) as client:
        r = client.post(
            "/api/ai-ops/approval/approve",
            headers={
                "X-Initiator": "ceo_chat",
            },
            json={"approval_id": "dummy", "session_id": "p0-enforced-approve-1"},
        )

    assert r.status_code == 403, r.text


def test_enforced_jwt_execute_raw_still_works(monkeypatch, tmp_path):
    _isolate_notion_armed_store(monkeypatch, tmp_path)
    app = _load_app()

    # Enforcement ON must not affect JWT privileged path.
    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT", "true")
    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT_TESTS", "true")
    monkeypatch.setenv("CEO_APPROVAL_TOKEN", "test_secret_123")

    with TestClient(app) as client:
        headers = auth_headers(
            monkeypatch,
            sub="p0-jwt-raw-exec-1",
            roles=["admin"],
            scopes=["raw_execute"],
        )
        r = client.post(
            "/api/execute/raw",
            headers=headers,
            json=_refresh_snapshot_payload(session_id="p0-jwt-session-1"),
        )

    assert r.status_code == 200, r.text


def test_enforced_jwt_approve_still_works(monkeypatch, tmp_path):
    _isolate_notion_armed_store(monkeypatch, tmp_path)
    app = _load_app()

    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT", "true")
    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT_TESTS", "true")
    monkeypatch.setenv("CEO_APPROVAL_TOKEN", "test_secret_123")

    with TestClient(app) as client:
        headers = auth_headers(
            monkeypatch,
            sub="p0-jwt-approver-1",
            roles=["ops_approver"],
        )
        # Provide minimal body; we only assert auth passes (400 is acceptable here).
        r = client.post(
            "/api/ai-ops/approval/approve",
            headers=headers,
            json={"session_id": "p0-jwt-approve-session-1"},
        )

    assert r.status_code == 400, r.text
    assert "approval_id" in (r.text or "")


@pytest.mark.parametrize(
    "token_env",
    [
        "",  # missing
        "   ",
    ],
)
def test_enforced_mode_missing_server_token_fails_close(monkeypatch, token_env):
    # tmp_path works with parametrize as a normal fixture.
    # Set store path before app import to avoid generating repo artifacts.
    from pathlib import Path

    tmp_path = Path(os.getcwd()) / ".pytest_cache" / "tmp" / "p0"
    tmp_path.mkdir(parents=True, exist_ok=True)
    _isolate_notion_armed_store(monkeypatch, tmp_path)

    app = _load_app()

    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT", "true")
    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT_TESTS", "true")
    monkeypatch.setenv("CEO_APPROVAL_TOKEN", token_env)

    with TestClient(app) as client:
        r = client.post(
            "/api/execute/raw",
            headers={"X-Initiator": "ceo_chat", "X-CEO-Token": "anything"},
            json=_refresh_snapshot_payload(session_id="p0-misconfig-1"),
        )

    assert r.status_code == 500, r.text
    assert "CEO_APPROVAL_TOKEN" in (r.text or "")
