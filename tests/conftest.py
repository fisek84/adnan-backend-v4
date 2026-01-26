"""Global pytest fixtures.

Goals:
- Deterministic tests: no real network calls (OpenAI/Notion/etc).
- Keep Starlette TestClient working (host=testserver).
"""

import os
import socket
import urllib.parse
from typing import Any, Callable

from pathlib import Path

import pytest


def _is_external_host(host: str | None) -> bool:
    h = (host or "").strip().lower()
    if not h:
        return False
    # Allow the in-process ASGI TestClient host and local dev.
    # NOTE: some tests use httpx AsyncClient(base_url="http://test").
    if h in {"testserver", "test", "localhost", "127.0.0.1", "0.0.0.0"}:
        return False
    return True


def _db_host_port(db_url: str) -> tuple[str | None, int | None]:
    """Best-effort parse of DB host/port for connection-availability checks."""
    u = (db_url or "").strip()
    if not u:
        return None, None

    # Keep sqlite URLs as-is (no external dependency).
    if u.startswith("sqlite"):
        return None, None

    try:
        parsed = urllib.parse.urlparse(u)
    except Exception:
        return None, None

    scheme = (parsed.scheme or "").lower()
    if not scheme.startswith("postgres"):
        return None, None

    host = parsed.hostname
    port = parsed.port or 5432
    return host, port


def _tcp_port_open(host: str, port: int, *, timeout_s: float = 0.15) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


@pytest.fixture
def anyio_backend():
    # Force AnyIO tests to run on asyncio only.
    # This avoids requiring optional dependency "trio".
    return "asyncio"


@pytest.fixture(autouse=True)
def _disable_external_network(monkeypatch: pytest.MonkeyPatch):
    """Fail-fast on any external HTTP request during tests."""
    os.environ.setdefault("TESTING", "1")

    # Keep tests stable even if developer shell exports prod write-guards.
    # Individual tests that validate enforcement/safe-mode explicitly set these env vars.
    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT", "false")
    monkeypatch.setenv("OPS_SAFE_MODE", "false")
    monkeypatch.delenv("CEO_APPROVAL_TOKEN", raising=False)

    # Test-safe memory storage: isolate file backend into a temp folder (Windows-safe).
    # This avoids cross-test contention and reduces the chance of file locking issues.
    # (If MEMORY_PATH is already set by the caller, respect it.)
    if not (os.getenv("MEMORY_PATH") or "").strip():
        # Use a stable per-process folder under .pytest_cache (no need for tmp_path_factory here).
        root = Path.cwd() / ".pytest_cache" / "memory"
        root.mkdir(parents=True, exist_ok=True)
        os.environ["MEMORY_PATH"] = str(root)

    # Force offline LLM behaviour in tests, even if developer has tokens set.
    # NOTE: Do not unset Notion env vars here; gateway boot validation may require them.
    for k in ("OPENAI_API_KEY", "CEO_ADVISOR_ASSISTANT_ID"):
        os.environ.pop(k, None)

    # Avoid flaky local/dev DB dependencies during unit tests.
    # If DATABASE_URL points to a local Postgres that isn't running, drop it so
    # callers that support "no DB configured" can fall back deterministically.
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url:
        host, port = _db_host_port(db_url)
        if host is not None:
            # Never allow tests to talk to external DB hosts.
            if _is_external_host(host):
                monkeypatch.delenv("DATABASE_URL", raising=False)
            elif port is not None and not _tcp_port_open(host, port):
                monkeypatch.delenv("DATABASE_URL", raising=False)

    try:
        import httpx

        orig_send = httpx.Client.send
        orig_async_send = httpx.AsyncClient.send

        def guarded_send(
            self: httpx.Client, request: httpx.Request, *args: Any, **kwargs: Any
        ):
            if _is_external_host(request.url.host):
                raise RuntimeError(
                    f"Network disabled in tests: {request.method} {request.url}"
                )
            return orig_send(self, request, *args, **kwargs)

        async def guarded_async_send(
            self: httpx.AsyncClient, request: httpx.Request, *args: Any, **kwargs: Any
        ):
            if _is_external_host(request.url.host):
                raise RuntimeError(
                    f"Network disabled in tests: {request.method} {request.url}"
                )
            return await orig_async_send(self, request, *args, **kwargs)

        monkeypatch.setattr(httpx.Client, "send", guarded_send, raising=True)
        monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send, raising=True)
    except Exception:
        # If httpx isn't importable for some reason, continue.
        pass

    # Also guard requests (some libs use it).
    try:
        import requests

        orig_request: Callable[..., Any] = requests.sessions.Session.request

        def guarded_requests(
            self: requests.sessions.Session,
            method: str,
            url: str,
            *args: Any,
            **kwargs: Any,
        ):
            try:
                import urllib.parse

                host = urllib.parse.urlparse(url).hostname
            except Exception:
                host = None
            if _is_external_host(host):
                raise RuntimeError(f"Network disabled in tests: {method} {url}")
            return orig_request(self, method, url, *args, **kwargs)

        monkeypatch.setattr(
            requests.sessions.Session, "request", guarded_requests, raising=True
        )
    except Exception:
        pass
