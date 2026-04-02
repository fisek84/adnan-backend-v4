from __future__ import annotations

import base64
import hashlib
import hmac
import json
import importlib
from pathlib import Path
import time
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _make_hs256_jwt(*, secret: str, claims: Dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    claims_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{claims_b64}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{claims_b64}.{_b64url(sig)}"


def _set_auth_env(monkeypatch: pytest.MonkeyPatch, *, secret: str) -> None:
    monkeypatch.setenv("AUTH_JWT_ALLOWED_ALGS", "HS256")
    monkeypatch.setenv("AUTH_JWT_ISSUER", "test-issuer")
    monkeypatch.setenv("AUTH_JWT_AUDIENCE", "test-audience")
    monkeypatch.setenv("AUTH_JWT_SECRET", secret)


def _token_for(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sub: str,
    roles: List[str],
    secret: str,
) -> str:
    _set_auth_env(monkeypatch, secret=secret)
    now = int(time.time())
    claims = {
        "iss": "test-issuer",
        "aud": "test-audience",
        "sub": sub,
        "exp": now + 3600,
        "nbf": now - 10,
        "iat": now,
        "roles": roles,
    }
    return _make_hs256_jwt(secret=secret, claims=claims)


def _client_without_boot(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from gateway import gateway_server

    async def _noop(_request):
        return None

    async def _boot_stub():
        # Minimal boot stub: only reload persistent Notion ARM store.
        from services import notion_armed_store

        notion_armed_store.load()
        setattr(gateway_server, "_BOOT_READY", True)

    monkeypatch.setattr(gateway_server, "_boot_once", _boot_stub, raising=True)
    monkeypatch.setattr(gateway_server, "_ensure_boot_if_needed", _noop, raising=True)
    return TestClient(gateway_server.app)


def test_arm_persists_reload_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    store_path = tmp_path / "notion_armed_store.json"
    monkeypatch.setenv("NOTION_ARMED_STORE_PATH", str(store_path))

    client = _client_without_boot(monkeypatch)

    # 401: missing token
    r1 = client.post("/api/notion-ops/toggle", json={"session_id": "s1", "armed": True})
    assert r1.status_code == 401

    secret = "test-secret"

    # 403: valid principal but missing required role.
    tok_user = _token_for(monkeypatch, sub="user-1", roles=["user"], secret=secret)
    r2 = client.post(
        "/api/notion-ops/toggle",
        headers={"Authorization": f"Bearer {tok_user}"},
        json={"session_id": "s1", "armed": True},
    )
    assert r2.status_code == 403

    # 200: admin can ARM.
    tok_admin = _token_for(monkeypatch, sub="admin-1", roles=["admin"], secret=secret)
    r3 = client.post(
        "/api/notion-ops/toggle",
        headers={"Authorization": f"Bearer {tok_admin}"},
        json={"session_id": "s1", "armed": True},
    )
    assert r3.status_code == 200
    data = r3.json()
    assert data.get("ok") is True
    assert data.get("principal_sub") == "admin-1"
    assert data.get("armed") is True

    assert store_path.exists()
    parsed = json.loads(store_path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    principals = parsed.get("principals")
    assert isinstance(principals, dict)
    st = principals.get("admin-1")
    assert isinstance(st, dict)
    assert st.get("principal_sub") == "admin-1"
    assert st.get("armed") is True
    assert st.get("armed_by_sub") == "admin-1"

    # State is keyed by principal.sub, not by session_id.
    assert principals.get("s1") is None

    # Simulated restart: reload store module and ensure state is reloaded from disk.
    import services.notion_armed_store as nas

    importlib.reload(nas)
    nas.load()
    reloaded = nas.get("admin-1")
    assert reloaded.get("armed") is True

    # Armed principal can write.
    r4 = client.post(
        "/api/notion-ops/bulk/create",
        headers={"Authorization": f"Bearer {tok_admin}"},
        json={"items": []},
    )
    assert r4.status_code == 200

    # Unarmed principal cannot write.
    r5 = client.post(
        "/api/notion-ops/bulk/create",
        headers={"Authorization": f"Bearer {tok_user}"},
        json={"items": []},
    )
    assert r5.status_code == 403
    assert "notion_ops_disarmed" in (r5.text or "")

    # DISARM admin and ensure write is blocked after reload.
    r6 = client.post(
        "/api/notion-ops/toggle",
        headers={"Authorization": f"Bearer {tok_admin}"},
        json={"armed": False},
    )
    assert r6.status_code == 200
    importlib.reload(nas)
    nas.load()
    assert nas.get("admin-1").get("armed") is False

    r7 = client.post(
        "/api/notion-ops/bulk/update",
        headers={"Authorization": f"Bearer {tok_admin}"},
        json={"updates": []},
    )
    assert r7.status_code == 403
    assert "notion_ops_disarmed" in (r7.text or "")

    # Fail-closed: if the persistent store is unavailable, writes must block.
    monkeypatch.setattr(
        nas,
        "get",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
        raising=True,
    )
    r8 = client.post(
        "/api/notion-ops/bulk/create",
        headers={"Authorization": f"Bearer {tok_admin}"},
        json={"items": []},
    )
    assert r8.status_code == 503
    assert "notion_armed_store_unavailable" in (r8.text or "")
