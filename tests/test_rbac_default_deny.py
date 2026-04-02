from __future__ import annotations

import json

import pytest


def test_privileged_action_is_denied_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path):
	# Ensure no config file is discovered.
	monkeypatch.chdir(tmp_path)
	monkeypatch.delenv("RBAC_CONFIG_JSON", raising=False)

	from services.rbac_service import RBACService

	rbac = RBACService()
	assert rbac.get_role_for_initiator("alice") == "user"
	assert rbac.is_allowed(initiator="alice", action="notion_write") is False


def test_privileged_action_requires_explicit_policy_allow(monkeypatch: pytest.MonkeyPatch, tmp_path):
	monkeypatch.chdir(tmp_path)
	monkeypatch.setenv(
		"RBAC_CONFIG_JSON",
		json.dumps({"role_actions": {"user": ["notion_write"]}}),
	)

	from services.rbac_service import RBACService

	rbac = RBACService()
	assert rbac.is_allowed(initiator="alice", action="notion_write") is True
