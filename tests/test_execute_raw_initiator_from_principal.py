from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.auth_utils import auth_headers


def _load_app():
	try:
		from gateway.gateway_server import app  # type: ignore

		return app
	except Exception:
		from main import app  # type: ignore

		return app


def _seed_gateway_env(monkeypatch) -> None:
	# Keep boot deterministic/offline.
	monkeypatch.setenv("GATEWAY_SKIP_KNOWLEDGE_SYNC", "1")

	# Minimal Notion env required by boot paths used in execute/raw tests.
	monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
	monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
	monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
	monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")


def test_execute_raw_rejects_spoofed_initiator_top_level(monkeypatch):
	"""SEC-202 regression lock: body.initiator must be rejected (cannot spoof)."""
	app = _load_app()
	client = TestClient(app)
	_seed_gateway_env(monkeypatch)

	principal_sub = "user_A"

	r = client.post(
		"/api/execute/raw",
		headers=auth_headers(
			None,
			sub=principal_sub,
			roles=["admin"],
			scopes=["raw_execute"],
		),
		json={
			"command": "create_task",
			"intent": "create_task",
			"initiator": "user_B",  # SPOOF attempt
			"params": {"title": "T"},
			"metadata": {"session_id": f"s-{uuid.uuid4().hex}"},
		},
	)

	assert r.status_code == 400, r.text
	body = r.json()
	detail = body.get("detail")
	assert isinstance(detail, str)
	assert "initiator" in detail
	assert "not allowed" in detail.lower()


def test_execute_raw_rejects_spoofed_initiator_nested(monkeypatch):
	"""SEC-202 regression lock: nested initiator fields must be rejected too."""
	app = _load_app()
	client = TestClient(app)
	_seed_gateway_env(monkeypatch)

	principal_sub = "user_A"

	# Attempt 1: params.initiator
	r1 = client.post(
		"/api/execute/raw",
		headers=auth_headers(
			None,
			sub=principal_sub,
			roles=["admin"],
			scopes=["raw_execute"],
		),
		json={
			"command": "create_task",
			"intent": "create_task",
			"params": {"initiator": "user_B", "title": "T"},
			"metadata": {"session_id": f"s-{uuid.uuid4().hex}"},
		},
	)
	assert r1.status_code == 400, r1.text
	d1 = (r1.json() or {}).get("detail")
	assert isinstance(d1, str)
	assert "params.initiator" in d1

	# Attempt 2: params.ai_command.initiator
	r2 = client.post(
		"/api/execute/raw",
		headers=auth_headers(
			None,
			sub=principal_sub,
			roles=["admin"],
			scopes=["raw_execute"],
		),
		json={
			"command": "create_task",
			"intent": "create_task",
			"params": {"ai_command": {"initiator": "user_B", "params": {}}},
			"metadata": {"session_id": f"s-{uuid.uuid4().hex}"},
		},
	)
	assert r2.status_code == 400, r2.text
	d2 = (r2.json() or {}).get("detail")
	assert isinstance(d2, str)
	assert "params.ai_command.initiator" in d2


def test_execute_raw_binds_command_initiator_to_principal_sub(monkeypatch):
	"""Regression lock: in the success path, command.initiator == principal.sub."""
	app = _load_app()
	client = TestClient(app)
	_seed_gateway_env(monkeypatch)

	principal_sub = "user_A"
	session_id = f"s-{uuid.uuid4().hex}"

	r = client.post(
		"/api/execute/raw",
		headers=auth_headers(
			None,
			sub=principal_sub,
			roles=["admin"],
			scopes=["raw_execute"],
		),
		json={
			"command": "create_task",
			"intent": "create_task",
			"params": {"title": "Test task"},
			"metadata": {"session_id": session_id},
		},
	)

	assert r.status_code == 200, r.text
	body = r.json()

	# /api/execute/raw creates an approval and returns BLOCKED.
	assert body.get("execution_state") == "BLOCKED"
	assert isinstance(body.get("approval_id"), str) and body.get("approval_id")
	assert isinstance(body.get("execution_id"), str) and body.get("execution_id")

	cmd = body.get("command")
	assert isinstance(cmd, dict)
	assert cmd.get("initiator") == principal_sub

	md = cmd.get("metadata")
	assert isinstance(md, dict)
	assert md.get("principal_sub") == principal_sub

