# services/identity_loader.py

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# GLOBAL CACHE (READ-ONLY, PROCESS LOCAL)
# ============================================================

_CACHE: Dict[str, Dict[str, Any]] = {}

# ============================================================
# CORE JSON LOADER (UTF-8 BOM SAFE)
# ============================================================


def load_json_file(path: str) -> Dict[str, Any]:
    """
    Loads JSON file safely.
    - UTF-8 BOM safe
    - Deterministic errors
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"[IDENTITY] File not found: {path}")

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"[IDENTITY] JSON root must be object: {path}")
        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"[IDENTITY] Invalid JSON in {path}: {e}") from e


# ============================================================
# PATH RESOLUTION (ENV OVERRIDE + RUNTIME SAFE)
# ============================================================


def resolve_path(filename: str) -> str:
    """
    Resolve identity file path.

    Priority:
    1) IDENTITY_PATH env
    2) <repo_root>/identity
    """
    env_base = (os.getenv("IDENTITY_PATH") or "").strip()
    if env_base:
        return os.path.join(os.path.abspath(env_base), filename)

    current_dir = os.path.dirname(os.path.abspath(__file__))  # /app/services
    project_root = os.path.abspath(os.path.join(current_dir, ".."))
    identity_dir = os.path.join(project_root, "identity")
    return os.path.join(identity_dir, filename)


# ============================================================
# VALIDATION (STRICT, FAIL FAST)
# ============================================================


def validate_identity_payload(
    payload: Dict[str, Any], *, required_keys: list, name: str
) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"[IDENTITY] {name} must be JSON object")
    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise ValueError(f"[IDENTITY] {name} missing keys: {missing}")


def validate_agent_definition(agent_id: str, agent: Dict[str, Any]) -> None:
    required = ["type", "capabilities", "enabled"]
    missing = [k for k in required if k not in agent]
    if missing:
        raise ValueError(f"[AGENTS] Agent '{agent_id}' missing keys: {missing}")

    if not isinstance(agent["capabilities"], list):
        raise ValueError(f"[AGENTS] Agent '{agent_id}' capabilities must be list")
    if not isinstance(agent["enabled"], bool):
        raise ValueError(f"[AGENTS] Agent '{agent_id}' enabled must be boolean")


# ============================================================
# INTERNAL: LOAD + CACHE
# ============================================================


def _load_cached(key: str, loader) -> Dict[str, Any]:
    if key in _CACHE:
        return _CACHE[key]
    data = loader()
    _CACHE[key] = data
    return data


# ============================================================
# LOADERS (SSOT)
# ============================================================


def load_adnan_identity() -> Dict[str, Any]:
    return _load_cached(
        "identity",
        lambda: _validated(
            load_json_file(resolve_path("identity.json")),
            required_keys=["name", "role", "version"],
            name="identity.json",
        ),
    )


def load_adnan_memory() -> Dict[str, Any]:
    return _load_cached(
        "memory",
        lambda: _validated(
            load_json_file(resolve_path("memory.json")),
            required_keys=["short_term", "long_term"],
            name="memory.json",
        ),
    )


def load_adnan_kernel() -> Dict[str, Any]:
    return _load_cached(
        "kernel",
        lambda: _validated(
            load_json_file(resolve_path("kernel.json")),
            required_keys=["principles", "constraints"],
            name="kernel.json",
        ),
    )


def load_adnan_static_memory() -> Dict[str, Any]:
    return _load_cached(
        "static_memory",
        lambda: _validated(
            load_json_file(resolve_path("static_memory.json")),
            required_keys=["facts"],
            name="static_memory.json",
        ),
    )


def load_adnan_mode() -> Dict[str, Any]:
    return _load_cached(
        "mode",
        lambda: _validated(
            load_json_file(resolve_path("mode.json")),
            required_keys=["current_mode"],
            name="mode.json",
        ),
    )


def load_adnan_state() -> Dict[str, Any]:
    return _load_cached(
        "state",
        lambda: _validated(
            load_json_file(resolve_path("state.json")),
            required_keys=["status"],
            name="state.json",
        ),
    )


def load_decision_engine_config() -> Dict[str, Any]:
    return _load_cached(
        "decision_engine",
        lambda: _validated(
            load_json_file(resolve_path("decision_engine.json")),
            required_keys=["strategy"],
            name="decision_engine.json",
        ),
    )


# ============================================================
# AGENTS
# ============================================================


def load_agents_identity() -> Dict[str, Dict[str, Any]]:
    def _load() -> Dict[str, Dict[str, Any]]:
        data = load_json_file(resolve_path("agents.json"))
        for agent_id, agent in data.items():
            if not isinstance(agent, dict):
                raise ValueError(f"[AGENTS] '{agent_id}' must be object")
            validate_agent_definition(agent_id, agent)
        return data

    return _load_cached("agents", _load)


# ============================================================
# CEO IDENTITY PACK (READ-ONLY, FAIL-SOFT)
# ============================================================


def load_ceo_identity_pack() -> Dict[str, Any]:
    pack: Dict[str, Any] = {
        "available": True,
        "source": "identity_loader",
        "identity": None,
        "kernel": None,
        "decision_engine": None,
        "static_memory": None,
        "memory": None,
        "agents": None,
        "errors": [],
    }

    def _try(label: str, fn) -> None:
        try:
            pack[label] = fn()
        except Exception as e:
            pack["errors"].append({"section": label, "error": str(e)})

    _try("identity", load_adnan_identity)
    _try("kernel", load_adnan_kernel)
    _try("decision_engine", load_decision_engine_config)
    _try("static_memory", load_adnan_static_memory)
    _try("memory", load_adnan_memory)
    _try("agents", load_agents_identity)

    if pack["identity"] is None and pack["kernel"] is None:
        pack["available"] = False

    return pack


# ============================================================
# BACKWARD COMPAT (DO NOT REMOVE)
# ============================================================


def load_identity() -> Dict[str, Any]:
    return load_adnan_identity()


def load_mode() -> Dict[str, Any]:
    return load_adnan_mode()


def load_state() -> Dict[str, Any]:
    return load_adnan_state()


# ============================================================
# HELPERS
# ============================================================


def _validated(
    data: Dict[str, Any], *, required_keys: list, name: str
) -> Dict[str, Any]:
    validate_identity_payload(data, required_keys=required_keys, name=name)
    return data
