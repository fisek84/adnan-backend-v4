from __future__ import annotations

import asyncio

import pytest


def test_write_requires_approval_creates_approval_and_no_side_effect(monkeypatch: pytest.MonkeyPatch):
	from services.write_gateway.write_gateway import PolicyDecision, WriteGateway

	handler_called = {"called": False}
	approval_called = {"called": False}

	async def _handler(_env):
		handler_called["called"] = True
		return {"ok": True}

	async def _policy(_env):
		return PolicyDecision(
			decision="requires_approval",
			reason="unit_requires_approval",
			approval_payload={"k": "v"},
			approval_id=None,
		)

	async def _approval_creator(_env, _payload):
		approval_called["called"] = True
		return "appr-unit-1"

	wg = WriteGateway(policy_evaluator=_policy, approval_creator=_approval_creator)
	wg.register_handler("demo_write", _handler)

	cmd = {
		"command": "demo_write",
		"actor_id": "alice",
		"resource": "unit",
		"payload": {"x": 1},
		"execution_id": "exec-401",
	}

	out = asyncio.run(wg.write(cmd))
	assert out.get("success") is False
	assert out.get("status") == "requires_approval"
	assert out.get("approval_id") == "appr-unit-1"

	assert approval_called["called"] is True
	assert handler_called["called"] is False


def test_write_gateway_cannot_be_used_without_approval_creator():
	from services.write_gateway.write_gateway import WriteGateway

	with pytest.raises(ValueError, match=r"approval_creator is required"):
		WriteGateway(approval_creator=None)  # type: ignore[arg-type]


def test_commit_write_blocks_when_approval_pending(monkeypatch: pytest.MonkeyPatch):
	from services.write_gateway.write_gateway import PolicyDecision, WriteGateway

	handler_called = {"called": False}

	class _FakeApprovals:
		def __init__(self):
			self._m = {"appr-pending": {"status": "pending"}}

		def get(self, approval_id: str):
			if approval_id not in self._m:
				raise KeyError("Approval not found")
			return dict(self._m[approval_id])

		def is_fully_approved(self, approval_id: str) -> bool:
			return approval_id in self._m and self._m[approval_id].get("status") == "approved"

	import services.approval_state_service as ass

	monkeypatch.setattr(ass, "get_approval_state", lambda: _FakeApprovals(), raising=True)

	async def _handler(_env):
		handler_called["called"] = True
		return {"ok": True}

	async def _policy(_env):
		return PolicyDecision(decision="allow", reason="unit_allow")

	async def _approval_creator(_env, _payload):
		return "appr-new"

	wg = WriteGateway(policy_evaluator=_policy, approval_creator=_approval_creator)
	wg.register_handler("demo_write", _handler)

	out = asyncio.run(
		wg.write(
			{
				"command": "demo_write",
				"actor_id": "alice",
				"resource": "unit",
				"payload": {"x": 1},
				"execution_id": "exec-402",
				"approval_id": "appr-pending",
			}
		)
	)

	assert out.get("success") is False
	assert out.get("status") == "requires_approval"
	assert out.get("approval_id") == "appr-pending"
	assert handler_called["called"] is False


def test_commit_write_blocks_when_approval_rejected_or_invalid(monkeypatch: pytest.MonkeyPatch):
	from services.write_gateway.write_gateway import PolicyDecision, WriteGateway

	handler_called = {"called": False}

	class _FakeApprovals:
		def __init__(self):
			self._m = {"appr-rejected": {"status": "rejected"}}

		def get(self, approval_id: str):
			if approval_id not in self._m:
				raise KeyError("Approval not found")
			return dict(self._m[approval_id])

		def is_fully_approved(self, approval_id: str) -> bool:
			return approval_id in self._m and self._m[approval_id].get("status") == "approved"

	import services.approval_state_service as ass

	monkeypatch.setattr(ass, "get_approval_state", lambda: _FakeApprovals(), raising=True)

	async def _handler(_env):
		handler_called["called"] = True
		return {"ok": True}

	async def _policy(_env):
		return PolicyDecision(decision="allow", reason="unit_allow")

	async def _approval_creator(_env, _payload):
		return "appr-new"

	wg = WriteGateway(policy_evaluator=_policy, approval_creator=_approval_creator)
	wg.register_handler("demo_write", _handler)

	out1 = asyncio.run(
		wg.write(
			{
				"command": "demo_write",
				"actor_id": "alice",
				"resource": "unit",
				"payload": {"x": 1},
				"execution_id": "exec-402-1",
				"approval_id": "appr-rejected",
			}
		)
	)
	assert out1.get("success") is False
	assert out1.get("status") == "rejected"
	assert handler_called["called"] is False

	out2 = asyncio.run(
		wg.write(
			{
				"command": "demo_write",
				"actor_id": "alice",
				"resource": "unit",
				"payload": {"x": 1},
				"execution_id": "exec-402-2",
				"approval_id": "appr-missing",
			}
		)
	)
	assert out2.get("success") is False
	assert out2.get("status") == "rejected"
	assert handler_called["called"] is False


def test_commit_write_allows_only_when_approval_approved(monkeypatch: pytest.MonkeyPatch):
	from services.write_gateway.write_gateway import PolicyDecision, WriteGateway

	handler_called = {"called": False}

	class _FakeApprovals:
		def __init__(self):
			self._m = {"appr-ok": {"status": "approved"}}

		def get(self, approval_id: str):
			if approval_id not in self._m:
				raise KeyError("Approval not found")
			return dict(self._m[approval_id])

		def is_fully_approved(self, approval_id: str) -> bool:
			return approval_id in self._m and self._m[approval_id].get("status") == "approved"

	import services.approval_state_service as ass

	monkeypatch.setattr(ass, "get_approval_state", lambda: _FakeApprovals(), raising=True)

	async def _handler(_env):
		handler_called["called"] = True
		return {"ok": True}

	async def _policy(_env):
		return PolicyDecision(decision="allow", reason="unit_allow")

	async def _approval_creator(_env, _payload):
		return "appr-new"

	wg = WriteGateway(policy_evaluator=_policy, approval_creator=_approval_creator)
	wg.register_handler("demo_write", _handler)

	out = asyncio.run(
		wg.write(
			{
				"command": "demo_write",
				"actor_id": "alice",
				"resource": "unit",
				"payload": {"x": 1},
				"execution_id": "exec-402-ok",
				"approval_id": "appr-ok",
			}
		)
	)
	assert out.get("success") is True
	assert out.get("status") in ("applied", "replayed")
	assert handler_called["called"] is True
