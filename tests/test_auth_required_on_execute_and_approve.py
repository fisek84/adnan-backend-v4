from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from models.ai_command import AICommand
from services.auth.dependencies import require_principal, require_role, require_scope
from services.auth.principal import Principal


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


def _token_for(
	monkeypatch: pytest.MonkeyPatch,
	*,
	sub: str,
	roles: list[str] | None = None,
	scopes: str | list[str] | None = None,
	issuer: str = "test-issuer",
	audience: str | list[str] = "test-audience",
	exp_offset: int = 3600,
	nbf_offset: int = -10,
	secret: str,
) -> str:
	_set_auth_env(monkeypatch, secret=secret)
	now = int(time.time())
	claims: dict[str, object] = {
		"iss": issuer,
		"aud": audience,
		"sub": sub,
		"exp": now + exp_offset,
		"nbf": now + nbf_offset,
		"iat": now,
	}
	if roles is not None:
		claims["roles"] = roles
	if scopes is not None:
		claims["scope"] = scopes
	return _make_hs256_jwt(secret=secret, claims=claims)


def _dependency_test_client() -> TestClient:
	app = FastAPI()

	@app.get("/principal")
	def _principal_route(_principal: Principal = Depends(require_principal)):
		return {"ok": True}

	@app.get("/role")
	def _role_route(_principal: Principal = Depends(require_role("admin"))):
		return {"ok": True}

	@app.get("/scope")
	def _scope_route(_principal: Principal = Depends(require_scope("write"))):
		return {"ok": True}

	return TestClient(app)


def _client_without_boot(monkeypatch: pytest.MonkeyPatch) -> TestClient:
	from gateway import gateway_server

	async def _noop(_request):
		return None

	monkeypatch.setattr(gateway_server, "_ensure_boot_if_needed", _noop, raising=True)
	return TestClient(gateway_server.app)


def test_non_chat_routes_require_auth_and_chat_stays_public(monkeypatch: pytest.MonkeyPatch):
	client = _client_without_boot(monkeypatch)

	# /api/chat must remain public (no auth). We assert it is NOT a 401/403.
	chat = client.post("/api/chat", json={"message": "ping"})
	assert chat.status_code not in (401, 403)

	# Non-chat routes in BE-602 scope must be 401 without token.
	cases = [
		("GET", "/health", None),
		("GET", "/ready", None),
		("GET", "/api/ceo-console/status", None),
		("GET", "/api/goals/all", None),
		("GET", "/api/tasks/all", None),
		("GET", "/api/notion-ops/databases", None),
		("POST", "/api/notion-ops/toggle", {"session_id": "s1", "armed": False}),
		("POST", "/api/notion/read", {"mode": "page_by_title", "query": "x"}),
		("POST", "/api/notion-ops/bulk/query", {"queries": []}),
		("POST", "/api/notion-ops/bulk/create", {"items": []}),
		("GET", "/databases", None),
		("GET", "/api/databases", None),
	]

	for method, path, body in cases:
		if method == "GET":
			resp = client.get(path)
		else:
			resp = client.post(path, json=body)
		assert resp.status_code == 401, f"expected 401 for {method} {path}, got {resp.status_code}"


def test_principal_from_claims_maps_verified_claims_deterministically():
	principal = Principal.from_claims(
		{
			"sub": "user-1",
			"roles": ["admin", "ceo", "admin"],
			"scope": "read write",
			"tenant": "tenant-a",
			"extra": "kept-in-raw-claims",
		}
	)

	assert principal.sub == "user-1"
	assert principal.roles == {"admin", "ceo"}
	assert principal.scopes == {"read", "write"}
	assert principal.tenant == "tenant-a"
	assert principal.raw_claims.get("extra") == "kept-in-raw-claims"


@pytest.mark.parametrize("claims", [{}, {"sub": None}, {"sub": "   "}])
def test_principal_from_claims_requires_non_empty_sub(claims):
	with pytest.raises(ValueError):
		Principal.from_claims(claims)


def test_principal_from_claims_normalizes_roles_scopes_and_tenant_fallbacks():
	principal = Principal.from_claims(
		{
			"sub": "user-2",
			"role": "operator",
			"scp": ["alpha", "beta", "alpha"],
			"tid": "tenant-b",
		}
	)

	assert principal.roles == {"operator"}
	assert principal.scopes == {"alpha", "beta"}
	assert principal.tenant == "tenant-b"


def test_require_principal_returns_401_for_missing_and_invalid_auth(monkeypatch: pytest.MonkeyPatch):
	client = _dependency_test_client()
	secret = "test-secret"
	_set_auth_env(monkeypatch, secret=secret)

	r1 = client.get("/principal")
	assert r1.status_code == 401

	r2 = client.get("/principal", headers={"Authorization": "Bearer not-a-jwt"})
	assert r2.status_code == 401


@pytest.mark.parametrize(
	"token_kwargs",
	[
		{"exp_offset": -60},
		{"issuer": "wrong-issuer"},
		{"audience": "wrong-audience"},
		{"nbf_offset": 600},
	],
)
def test_require_principal_returns_401_for_invalid_verified_jwt_states(
	monkeypatch: pytest.MonkeyPatch,
	token_kwargs: dict[str, object],
):
	client = _dependency_test_client()
	tok = _token_for(
		monkeypatch,
		sub="user-1",
		roles=["admin"],
		secret="test-secret",
		**token_kwargs,
	)

	resp = client.get("/principal", headers={"Authorization": f"Bearer {tok}"})
	assert resp.status_code == 401


def test_require_role_returns_403_for_valid_principal_without_required_role(monkeypatch: pytest.MonkeyPatch):
	client = _dependency_test_client()
	tok = _token_for(
		monkeypatch,
		sub="user-1",
		roles=["user"],
		secret="test-secret",
	)

	resp = client.get("/role", headers={"Authorization": f"Bearer {tok}"})
	assert resp.status_code == 403


def test_require_scope_returns_403_for_valid_principal_without_required_scope(monkeypatch: pytest.MonkeyPatch):
	client = _dependency_test_client()
	tok = _token_for(
		monkeypatch,
		sub="user-1",
		roles=["admin"],
		scopes="read",
		secret="test-secret",
	)

	resp = client.get("/scope", headers={"Authorization": f"Bearer {tok}"})
	assert resp.status_code == 403


def test_execute_endpoints_require_auth_and_privileged_role(monkeypatch: pytest.MonkeyPatch):
	client = _client_without_boot(monkeypatch)
	secret = "test-secret"

	user_tok = _token_for(
		monkeypatch,
		sub="user-1",
		roles=["user"],
		secret=secret,
	)

	for path, body in (
		("/api/execute", {"text": "ping"}),
		("/api/execute/preview", {"command": "refresh_snapshot", "intent": "refresh_snapshot", "params": {}}),
	):
		r1 = client.post(path, json=body)
		assert r1.status_code == 401

		r2 = client.post(path, headers={"Authorization": f"Bearer {user_tok}"}, json=body)
		assert r2.status_code == 403


def test_execute_and_preview_remain_functional_for_privileged_principal(monkeypatch: pytest.MonkeyPatch):
	from gateway import gateway_server

	client = _client_without_boot(monkeypatch)
	admin_tok = _token_for(
		monkeypatch,
		sub="admin-1",
		roles=["admin"],
		secret="test-secret",
	)

	class _DummyTranslator:
		def translate(self, **_kwargs):
			return AICommand(command="noop", intent="noop", metadata={})

	class _DummyApprovalState:
		def create(self, **_kwargs):
			return {"approval_id": "appr-1"}

	class _DummyRegistry:
		def register(self, *_args, **_kwargs):
			return None

	class _DummyOrchestrator:
		def __init__(self):
			self.registry = _DummyRegistry()

		async def execute(self, _command):
			return {"status": "BLOCKED", "execution_state": "BLOCKED"}

	monkeypatch.setattr(
		gateway_server,
		"_require_boot_services",
		lambda: (None, _DummyTranslator(), None, _DummyRegistry(), _DummyOrchestrator()),
		raising=True,
	)
	monkeypatch.setattr(
		gateway_server,
		"get_approval_state",
		lambda: _DummyApprovalState(),
		raising=True,
	)

	exec_resp = client.post(
		"/api/execute",
		headers={"Authorization": f"Bearer {admin_tok}"},
		json={"text": "ping"},
	)
	assert exec_resp.status_code == 200
	assert exec_resp.json().get("status") == "BLOCKED"

	preview_resp = client.post(
		"/api/execute/preview",
		headers={"Authorization": f"Bearer {admin_tok}"},
		json={"command": "refresh_snapshot", "intent": "refresh_snapshot", "params": {}},
	)
	assert preview_resp.status_code == 200
	assert preview_resp.json().get("ok") is True
