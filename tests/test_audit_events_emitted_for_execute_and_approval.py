from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException
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
	scopes: Optional[List[str]] = None,
	secret: str,
) -> str:
	_set_auth_env(monkeypatch, secret=secret)
	now = int(time.time())
	claims: Dict[str, Any] = {
		"iss": "test-issuer",
		"aud": "test-audience",
		"sub": sub,
		"exp": now + 3600,
		"nbf": now - 10,
		"iat": now,
		"roles": roles,
	}
	if scopes:
		claims["scope"] = " ".join(scopes)
	return _make_hs256_jwt(secret=secret, claims=claims)


def _event_of_type(events: list, event_type: str):
	for e in events:
		if getattr(e, "event_type", None) == event_type:
			return e
	return None


def test_audit_emits_for_auth_denied_401(monkeypatch: pytest.MonkeyPatch):
	from gateway.gateway_server import app
	from services.audit_log_service import get_audit_log_service

	audit = get_audit_log_service()
	audit.clear()

	client = TestClient(app)
	rid = "req-plat-502-401"
	resp = client.post(
		"/api/ai-ops/approval/approve",
		headers={"X-Request-ID": rid},
		json={"approval_id": "missing"},
	)
	assert resp.status_code == 401

	events = audit.list_events()
	e = _event_of_type(events, "auth_denied")
	assert e is not None, f"expected auth_denied event, got {[x.event_type for x in events]}"
	assert e.request_id == rid
	assert e.route == "/api/ai-ops/approval/approve"


def test_audit_emits_for_execute_start_raw_refresh_snapshot(monkeypatch: pytest.MonkeyPatch):
	from gateway import gateway_server
	from gateway.gateway_server import app
	from services.audit_log_service import get_audit_log_service

	audit = get_audit_log_service()
	audit.clear()

	def _boot_fail():
		raise HTTPException(status_code=503, detail="boot_not_ready")

	monkeypatch.setattr(gateway_server, "_require_boot_services", _boot_fail, raising=True)

	secret = "test-secret"
	tok = _token_for(
		monkeypatch,
		sub="admin-1",
		roles=["admin"],
		scopes=["raw_execute"],
		secret=secret,
	)

	client = TestClient(app)
	rid = "req-plat-502-exec-start"
	resp = client.post(
		"/api/execute/raw",
		headers={
			"Authorization": f"Bearer {tok}",
			"X-Request-ID": rid,
		},
		json={"command": "refresh_snapshot", "intent": "refresh_snapshot", "params": {}},
	)
	assert resp.status_code == 200

	events = audit.list_events()
	e = _event_of_type(events, "execute_start")
	assert e is not None, f"expected execute_start event, got {[x.event_type for x in events]}"
	assert e.request_id == rid
	assert e.principal_sub == "admin-1"
	assert "admin" in (e.principal_roles or [])
	assert e.route == "/api/execute/raw"
	assert e.result == "started"


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


def test_audit_emits_for_approval_approved(monkeypatch: pytest.MonkeyPatch):
	from gateway.gateway_server import app
	from services.approval_state_service import get_approval_state
	from services.audit_log_service import get_audit_log_service
	import routers.ai_ops_router as aor
	import uuid

	audit = get_audit_log_service()
	audit.clear()

	# Keep execution path deterministic.
	monkeypatch.setattr(aor, "_get_orchestrator", lambda: _DummyOrchestrator(), raising=True)
	monkeypatch.setattr(aor, "get_decision_outcome_registry", lambda: _DummyDOR(), raising=True)
	monkeypatch.setattr(aor, "_enrich_decision_record_with_snapshots", lambda x: x, raising=True)
	monkeypatch.setattr(aor, "_schedule_outcome_feedback_reviews", lambda *_a, **_k: None, raising=True)

	client = TestClient(app)
	state = get_approval_state()
	created = state.create(
		command="unit_test",
		payload_summary={"intent": "noop"},
		scope="unit_test",
		risk_level="low",
		execution_id=f"exec-plat-502-approval-{uuid.uuid4()}",
	)
	approval_id = created["approval_id"]

	secret = "test-secret"
	tok_ok = _token_for(
		monkeypatch,
		sub="ops-approver-1",
		roles=["ops_approver"],
		secret=secret,
	)
	rid = "req-plat-502-approval"
	resp = client.post(
		"/api/ai-ops/approval/approve",
		headers={
			"Authorization": f"Bearer {tok_ok}",
			"X-Request-ID": rid,
		},
		json={"approval_id": approval_id, "note": "ok"},
	)
	assert resp.status_code == 200

	events = audit.list_events()
	e = _event_of_type(events, "approval_approved")
	assert e is not None, f"expected approval_approved event, got {[x.event_type for x in events]}"
	assert e.request_id == rid
	assert e.principal_sub == "ops-approver-1"
	assert "ops_approver" in (e.principal_roles or [])
	assert e.approval_id == approval_id
	assert e.result == "approved"



def test_audit_emits_for_execute_resume_unit(monkeypatch: pytest.MonkeyPatch):
	import asyncio

	from models.ai_command import AICommand
	from services.audit_log_service import get_audit_log_service
	from services.execution_orchestrator import ExecutionOrchestrator

	audit = get_audit_log_service()
	audit.clear()

	class _Reg:
		def __init__(self, cmd: AICommand) -> None:
			self._cmd = cmd

		def get(self, _: str):
			return self._cmd

	cmd = AICommand(
		command="noop",
		intent="noop",
		params={},
		initiator="admin-1",
		metadata={"request_id": "req-plat-502-resume"},
		approval_id="appr-1",
		execution_id="exec-1",
	)

	class _Approvals:
		def is_fully_approved(self, _: Any) -> bool:
			return True

	async def _stub_execute_after_approval(self, _cmd: AICommand) -> Dict[str, Any]:
		return {"ok": True, "execution_state": "COMPLETED"}

	# Avoid __init__ heavy deps.
	orch = ExecutionOrchestrator.__new__(ExecutionOrchestrator)
	orch.registry = _Reg(cmd)
	orch.approvals = _Approvals()
	orch._execute_after_approval = _stub_execute_after_approval.__get__(orch, ExecutionOrchestrator)

	out = asyncio.run(orch.resume("exec-1"))
	assert out.get("ok") is True

	events = audit.list_events()
	e = _event_of_type(events, "execute_resume")
	assert e is not None, f"expected execute_resume event, got {[x.event_type for x in events]}"
	assert e.request_id == "req-plat-502-resume"
	assert e.execution_id == "exec-1"
	assert e.approval_id == "appr-1"
