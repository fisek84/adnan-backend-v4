from __future__ import annotations

import asyncio
import json

import pytest


def _set_production_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate production: RENDER=true and not test mode.
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


def test_boot_fails_fast_when_jwt_config_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    _set_production_mode(monkeypatch)

    from gateway import gateway_server

    # Avoid unrelated env validations; this test targets PLAT-104 preflight.
    monkeypatch.setattr(
        gateway_server, "validate_runtime_env_or_raise", lambda: None, raising=True
    )

    # Ensure RBAC policy is present so failure is specifically JWT config.
    monkeypatch.setenv("RBAC_CONFIG_JSON", json.dumps({"role_actions": {"user": []}}))

    # Missing JWT envs.
    for k in (
        "AUTH_JWT_ALLOWED_ALGS",
        "AUTH_JWT_ISSUER",
        "AUTH_JWT_AUDIENCE",
        "AUTH_JWT_SECRET",
        "AUTH_JWT_PUBLIC_KEY_PEM",
    ):
        monkeypatch.delenv(k, raising=False)

    gateway_server._BOOT_READY = False
    gateway_server._BOOT_ERROR = None

    with pytest.raises(RuntimeError, match=r"PLAT-104: missing critical auth config"):
        asyncio.run(gateway_server._boot_once())


def test_boot_fails_fast_when_rbac_policy_missing_or_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    _set_production_mode(monkeypatch)

    from gateway import gateway_server

    monkeypatch.setattr(
        gateway_server, "validate_runtime_env_or_raise", lambda: None, raising=True
    )

    # Provide minimal JWT config so failure is specifically RBAC policy.
    monkeypatch.setenv("AUTH_JWT_ALLOWED_ALGS", "HS256")
    monkeypatch.setenv("AUTH_JWT_ISSUER", "issuer")
    monkeypatch.setenv("AUTH_JWT_AUDIENCE", "aud")
    monkeypatch.setenv("AUTH_JWT_SECRET", "secret")
    monkeypatch.delenv("AUTH_JWT_PUBLIC_KEY_PEM", raising=False)

    # No RBAC config via env and no config/rbac.json in tmp_path.
    monkeypatch.delenv("RBAC_CONFIG_JSON", raising=False)

    gateway_server._BOOT_READY = False
    gateway_server._BOOT_ERROR = None

    with pytest.raises(RuntimeError, match=r"PLAT-104: RBAC policy missing or empty"):
        asyncio.run(gateway_server._boot_once())
