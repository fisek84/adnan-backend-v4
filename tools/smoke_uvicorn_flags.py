import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class RunResult:
    port: int
    alive_after_probe: bool
    port_listening: bool
    status_health_services: int
    status_openapi: int
    log_path: str
    openapi_path: str


def _tcp_listening(host: str, port: int, timeout_s: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _is_port_free(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
        return True
    except OSError:
        return False


def _next_free_port(host: str, start_port: int, max_tries: int = 50) -> int:
    for p in range(start_port, start_port + max_tries):
        if _is_port_free(host, p):
            return p
    raise RuntimeError(f"No free port found starting at {start_port}")


def _http_status(url: str, timeout_s: float = 2.0) -> int:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return int(getattr(resp, "status", 200))
    except urllib.error.HTTPError as e:
        return int(getattr(e, "code", -1))
    except Exception:
        return -1


def _http_get_json(url: str, timeout_s: float = 4.0) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = resp.read()
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _extract_method_path_set(openapi: Dict[str, Any]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    paths = openapi.get("paths")
    if not isinstance(paths, dict):
        return out
    for path, item in paths.items():
        if not isinstance(path, str) or not isinstance(item, dict):
            continue
        for method in item.keys():
            if not isinstance(method, str):
                continue
            mm = method.upper()
            if mm == "HEAD":
                continue
            out.add((mm, path))
    return out


def _run_uvicorn_mode(
    *,
    port: int,
    enable_extra: bool,
    artifacts_dir: Path,
) -> RunResult:
    host = "127.0.0.1"
    mode_name = "on" if enable_extra else "off"
    log_path = artifacts_dir / f"uvicorn_{mode_name}.log"
    openapi_path = artifacts_dir / f"openapi_{mode_name}.json"

    env = os.environ.copy()
    env["ENABLE_EXTRA_ROUTERS"] = "true" if enable_extra else "false"

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "gateway.gateway_server:app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        "info",
        "--lifespan",
        "off",
    ]

    started_at = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=str(Path.cwd()),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Wait for port (max 6s)
    port_listening = False
    while time.time() - started_at < 6.0:
        if proc.poll() is not None:
            break
        if _tcp_listening(host, port, timeout_s=0.2):
            port_listening = True
            break
        time.sleep(0.15)

    # Probe endpoints (even if port didn't open, return -1)
    status_health_services = _http_status(f"http://{host}:{port}/health/services")
    status_openapi = _http_status(f"http://{host}:{port}/openapi.json")

    openapi = _http_get_json(f"http://{host}:{port}/openapi.json")
    if openapi is not None:
        _write_text(openapi_path, json.dumps(openapi, indent=2))
    else:
        _write_text(openapi_path, "")

    alive_after_probe = proc.poll() is None

    # Terminate and capture logs deterministically (avoid readline deadlocks on Windows).
    captured = ""

    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    try:
        out, _ = proc.communicate(timeout=2.0)
        captured = out or ""
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            out, _ = proc.communicate(timeout=2.0)
            captured = out or ""
        except Exception:
            captured = ""

    _write_text(log_path, captured)

    return RunResult(
        port=port,
        alive_after_probe=alive_after_probe,
        port_listening=port_listening,
        status_health_services=status_health_services,
        status_openapi=status_openapi,
        log_path=str(log_path),
        openapi_path=str(openapi_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test ENABLE_EXTRA_ROUTERS via OpenAPI"
    )
    parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="Base port: OFF binds exactly here, ON binds to port+1 (or next free)",
    )
    args = parser.parse_args()

    artifacts_dir = Path("artifacts") / "extra_routers"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Default explicit allowlist for clarity (matches the three extra routers)
    host = "127.0.0.1"
    off_port = int(args.port)
    if not _is_port_free(host, off_port):
        raise SystemExit(
            f"OFF port {off_port} is not free (hard requirement: bind exactly)"
        )

    preferred_on = off_port + 1
    on_port = (
        preferred_on
        if _is_port_free(host, preferred_on)
        else _next_free_port(host, preferred_on)
    )

    off = _run_uvicorn_mode(
        port=off_port,
        enable_extra=False,
        artifacts_dir=artifacts_dir,
    )
    on = _run_uvicorn_mode(
        port=on_port,
        enable_extra=True,
        artifacts_dir=artifacts_dir,
    )

    off_openapi = {}
    on_openapi = {}
    try:
        if off.openapi_path and Path(off.openapi_path).exists():
            txt = Path(off.openapi_path).read_text(encoding="utf-8").strip()
            if txt:
                off_openapi = json.loads(txt)
        if on.openapi_path and Path(on.openapi_path).exists():
            txt = Path(on.openapi_path).read_text(encoding="utf-8").strip()
            if txt:
                on_openapi = json.loads(txt)
    except Exception:
        pass

    off_set = _extract_method_path_set(off_openapi) if off_openapi else set()
    on_set = _extract_method_path_set(on_openapi) if on_openapi else set()
    new_routes = sorted(list(on_set - off_set), key=lambda x: (x[1], x[0]))
    print("NEW routes (METHOD, PATH) present in openapi_on but not openapi_off:")
    print(json.dumps(new_routes, indent=2))

    # Enterprise hard expectations for the feature-flagged extra routers.
    expected_on: list[tuple[str, str]] = [
        ("GET", "/api/sop/list"),
        ("GET", "/api/sop/get"),
        ("POST", "/api/adnan-ai/actions/"),
        ("GET", "/api/adnan-ai/identity"),
        ("GET", "/api/adnan-ai/kernel"),
        ("GET", "/api/adnan-ai/mode"),
        ("GET", "/api/adnan-ai/state"),
        ("GET", "/api/adnan-ai/decision-engine"),
    ]

    summary: Dict[str, Any] = {
        "off": {
            "port": off.port,
            "alive_after_probe": off.alive_after_probe,
            "port_listening": off.port_listening,
            "health_services": off.status_health_services,
            "openapi": off.status_openapi,
            "log_path": off.log_path,
            "openapi_path": off.openapi_path,
        },
        "on": {
            "port": on.port,
            "alive_after_probe": on.alive_after_probe,
            "port_listening": on.port_listening,
            "health_services": on.status_health_services,
            "openapi": on.status_openapi,
            "log_path": on.log_path,
            "openapi_path": on.openapi_path,
            "new_routes_vs_off": new_routes,
        },
    }

    out_path = artifacts_dir / "smoke_status.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))

    # Hard-fail if OpenAPI wasn't fetched or ON mode didn't show expected prefixes.
    if on.status_openapi != 200:
        raise SystemExit(2)

    missing_on = [rp for rp in expected_on if rp not in on_set]
    if missing_on:
        print("Missing expected routes in openapi_on:")
        print(json.dumps(missing_on, indent=2))
        raise SystemExit(3)

    unexpected_off = [rp for rp in expected_on if rp in off_set]
    if unexpected_off:
        print(
            "Unexpected routes present in openapi_off (should be absent when flag OFF):"
        )
        print(json.dumps(unexpected_off, indent=2))
        raise SystemExit(4)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
