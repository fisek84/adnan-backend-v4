from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
import time
from typing import Optional

import pytest
from fastapi import Request
from fastapi.testclient import TestClient


def _b64url(data: bytes) -> str:
	return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _make_hs256_jwt(*, secret: str, claims: dict[str, object]) -> str:
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


def _token_for(monkeypatch: pytest.MonkeyPatch, *, sub: str, roles: list[str], secret: str) -> str:
	_set_auth_env(monkeypatch, secret=secret)
	now = int(time.time())
	claims: dict[str, object] = {
		"iss": "test-issuer",
		"aud": "test-audience",
		"sub": sub,
		"exp": now + 3600,
		"nbf": now - 10,
		"iat": now,
		"roles": roles,
	}
	return _make_hs256_jwt(secret=secret, claims=claims)


def _client_with_probe(monkeypatch: pytest.MonkeyPatch) -> TestClient:
	from gateway import gateway_server as gateway_server_module

	gateway_server = importlib.reload(gateway_server_module)

	async def _noop(_request):
		return None

	monkeypatch.setattr(gateway_server, "_ensure_boot_if_needed", _noop, raising=True)
	app = gateway_server.app

	app.state._req_id_probe_installed = True
	app.state._last_req_id_seen = None

	@app.middleware("http")
	async def _probe_req_id_middleware(request: Request, call_next):
		response = await call_next(request)
		rid = getattr(getattr(request, "state", None), "req_id", None)
		app.state._last_req_id_seen = rid
		return response

	return TestClient(app)


def _last_req_id_seen() -> Optional[str]:
	from gateway.gateway_server import app

	rid = getattr(app.state, "_last_req_id_seen", None)
	return rid if isinstance(rid, str) else None


def test_request_without_x_request_id_gets_generated_and_propagated(monkeypatch: pytest.MonkeyPatch):
	client = _client_with_probe(monkeypatch)
	tok = _token_for(monkeypatch, sub="admin-1", roles=["admin"], secret="test-secret")
	resp = client.get("/health", headers={"Authorization": f"Bearer {tok}"})
	assert resp.status_code == 200

	rid = resp.headers.get("X-Request-ID")
	assert isinstance(rid, str) and rid.strip(), "response must include X-Request-ID"

	state_rid = _last_req_id_seen()
	assert state_rid == rid, "request.state.req_id must match response header"


def test_request_with_existing_x_request_id_is_echoed_and_state_matches(monkeypatch: pytest.MonkeyPatch):
	client = _client_with_probe(monkeypatch)
	tok = _token_for(monkeypatch, sub="admin-1", roles=["admin"], secret="test-secret")
	expected = "req-plat-501-123"
	resp = client.get(
		"/health",
		headers={"X-Request-ID": expected, "Authorization": f"Bearer {tok}"},
	)
	assert resp.status_code == 200
	assert resp.headers.get("X-Request-ID") == expected

	state_rid = _last_req_id_seen()
	assert state_rid == expected
