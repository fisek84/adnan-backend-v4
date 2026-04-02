from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

import pytest


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _make_hs256_jwt(*, secret: str, claims: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    claims_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{claims_b64}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{claims_b64}.{_b64url(sig)}"


def _set_env(name: str, value: str, monkeypatch: pytest.MonkeyPatch | None) -> None:
    if monkeypatch is not None:
        monkeypatch.setenv(name, value)
    else:
        os.environ[name] = value


def set_auth_env(
    monkeypatch: pytest.MonkeyPatch | None = None,
    *,
    secret: str = "test-secret",
) -> str:
    _set_env("AUTH_JWT_ALLOWED_ALGS", "HS256", monkeypatch)
    _set_env("AUTH_JWT_ISSUER", "test-issuer", monkeypatch)
    _set_env("AUTH_JWT_AUDIENCE", "test-audience", monkeypatch)
    _set_env("AUTH_JWT_SECRET", secret, monkeypatch)
    return secret


def token_for(
    monkeypatch: pytest.MonkeyPatch | None = None,
    *,
    sub: str,
    roles: list[str] | None = None,
    scopes: str | list[str] | None = None,
    secret: str = "test-secret",
    issuer: str = "test-issuer",
    audience: str | list[str] = "test-audience",
    exp_offset: int = 3600,
    nbf_offset: int = -10,
) -> str:
    set_auth_env(monkeypatch, secret=secret)
    now = int(time.time())
    claims: dict[str, Any] = {
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


def auth_headers(
    monkeypatch: pytest.MonkeyPatch | None = None,
    *,
    sub: str,
    roles: list[str] | None = None,
    scopes: str | list[str] | None = None,
    secret: str = "test-secret",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    token = token_for(
        monkeypatch,
        sub=sub,
        roles=roles,
        scopes=scopes,
        secret=secret,
    )
    headers = {"Authorization": f"Bearer {token}"}
    if extra:
        headers.update(extra)
    return headers
