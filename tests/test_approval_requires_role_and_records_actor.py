from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
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


class _DummyOrchestrator:
    async def resume(self, execution_id: str) -> Dict[str, Any]:
        return {
            "ok": True,
            "execution_id": execution_id,
            "execution_state": "COMPLETED",
            "result": {"ok": True},
        }


class _DummyDOR:
    def create_or_get_for_approval(self, **_: Any) -> Dict[str, Any]:
        return {}

    def set_execution_outcome(self, **_: Any) -> Dict[str, Any]:
        return {}

    def get_by_execution_id(self, _: str) -> Dict[str, Any]:
        return {}


def test_approve_requires_auth_and_role_and_records_actor(
    monkeypatch: pytest.MonkeyPatch,
):
    from gateway.gateway_server import app
    from services.approval_state_service import get_approval_state
    import routers.ai_ops_router as aor

    # Keep execution path deterministic.
    monkeypatch.setattr(
        aor, "_get_orchestrator", lambda: _DummyOrchestrator(), raising=True
    )
    monkeypatch.setattr(
        aor, "get_decision_outcome_registry", lambda: _DummyDOR(), raising=True
    )
    monkeypatch.setattr(
        aor, "_enrich_decision_record_with_snapshots", lambda x: x, raising=True
    )
    monkeypatch.setattr(
        aor, "_schedule_outcome_feedback_reviews", lambda *_a, **_k: None, raising=True
    )

    client = TestClient(app)

    state = get_approval_state()
    created = state.create(
        command="unit_test",
        payload_summary={"intent": "noop"},
        scope="unit_test",
        risk_level="low",
        execution_id=f"exec-test-be-203-{uuid.uuid4()}",
    )
    approval_id = created["approval_id"]

    # 401: missing token.
    r1 = client.post(
        "/api/ai-ops/approval/approve",
        json={"approval_id": approval_id, "note": "x"},
    )
    assert r1.status_code == 401
    after_401 = state.get(approval_id)
    assert after_401.get("status") == "pending"
    assert "approved_by_sub" not in after_401

    # 403: valid principal but missing role.
    secret = "test-secret"
    tok_user = _token_for(
        monkeypatch,
        sub="user-1",
        roles=["user"],
        secret=secret,
    )
    r2 = client.post(
        "/api/ai-ops/approval/approve",
        headers={"Authorization": f"Bearer {tok_user}"},
        json={"approval_id": approval_id, "note": "x"},
    )
    assert r2.status_code == 403
    after_403 = state.get(approval_id)
    assert after_403.get("status") == "pending"
    assert "approved_by_sub" not in after_403

    # 200: allowed role -> approved + attribution fields.
    req_id = "req-be-203-1"
    tok_ok = _token_for(
        monkeypatch,
        sub="ops-approver-1",
        roles=["ops_approver"],
        secret=secret,
    )
    r3 = client.post(
        "/api/ai-ops/approval/approve",
        headers={
            "Authorization": f"Bearer {tok_ok}",
            "X-Request-ID": req_id,
        },
        json={"approval_id": approval_id, "note": "approved"},
    )
    assert r3.status_code == 200

    approved = state.get(approval_id)
    assert approved.get("status") == "approved"
    assert approved.get("approved_by_sub") == "ops-approver-1"
    assert "ops_approver" in (approved.get("approved_by_roles") or [])
    assert isinstance(approved.get("approved_at"), str) and approved.get("approved_at")
    assert approved.get("request_id") == req_id
