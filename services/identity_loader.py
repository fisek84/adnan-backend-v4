# services/identity_loader.py

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict

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

    current_dir = os.path.dirname(os.path.abspath(__file__))  # .../services
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


# NOTE: kept for potential future use; NOT enforced unless schema is explicit.
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


def _load_cached(key: str, loader: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """
    Cache loader output by key.
    NOTE: Cache is process-local and assumes read-only files during process lifetime.
    """
    if key in _CACHE:
        return _CACHE[key]
    data = loader()
    _CACHE[key] = data
    return data


# ============================================================
# LOADERS (SSOT) â€” MATCH ACTUAL IDENTITY FILE SCHEMAS
# ============================================================


def load_adnan_identity() -> Dict[str, Any]:
    # This already loads successfully in your runtime test.
    return _load_cached(
        "identity",
        lambda: _validated(
            load_json_file(resolve_path("identity.json")),
            required_keys=["name", "role", "version"],
            name="identity.json",
        ),
    )


def load_adnan_kernel() -> Dict[str, Any]:
    # Based on your terminal output: kernel.json keys =
    # ['version','core_identity','immutable_laws','thinking_framework','communication_tone','system_safety']
    return _load_cached(
        "kernel",
        lambda: _validated(
            load_json_file(resolve_path("kernel.json")),
            required_keys=[
                "version",
                "core_identity",
                "immutable_laws",
                "thinking_framework",
                "communication_tone",
                "system_safety",
            ],
            name="kernel.json",
        ),
    )


def load_decision_engine_config() -> Dict[str, Any]:
    # Based on your terminal output: decision_engine.json keys = ['version','decision_engine']
    return _load_cached(
        "decision_engine",
        lambda: _validated(
            load_json_file(resolve_path("decision_engine.json")),
            required_keys=["version", "decision_engine"],
            name="decision_engine.json",
        ),
    )


def load_adnan_static_memory() -> Dict[str, Any]:
    # Based on your terminal output: static_memory.json keys = ['rules']
    return _load_cached(
        "static_memory",
        lambda: _validated(
            load_json_file(resolve_path("static_memory.json")),
            required_keys=["rules"],
            name="static_memory.json",
        ),
    )


def load_adnan_memory() -> Dict[str, Any]:
    # Based on your terminal output: memory.json keys include:
    # ['last_mode','last_state','trace','notes','dynamic_memory','agent_memory']
    # We validate only the key parts used as "memory payload".
    return _load_cached(
        "memory",
        lambda: _validated(
            load_json_file(resolve_path("memory.json")),
            required_keys=["dynamic_memory", "agent_memory"],
            name="memory.json",
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


# ============================================================
# AGENTS â€” MATCH ACTUAL SCHEMA: { "version": ..., "agents": {...} }
# ============================================================


def load_agents_identity() -> Dict[str, Any]:
    """
    Loads agents.json with actual schema:
      { "version": <...>, "agents": { "ceo_advisor": {...}, "notion_ops": {...}, ... } }

    NIJE POZNATO: full per-agent schema; therefore we only enforce that each agent entry is an object/dict.
    """

    def _load() -> Dict[str, Any]:
        data = load_json_file(resolve_path("agents.json"))
        validate_identity_payload(data, required_keys=["version", "agents"], name="agents.json")

        agents = data.get("agents")
        if not isinstance(agents, dict):
            raise ValueError("[AGENTS] 'agents' must be object")

        # Minimal validation: each agent entry must be an object.
        for agent_id, agent in agents.items():
            if not isinstance(agent_id, str) or not agent_id.strip():
                raise ValueError("[AGENTS] agent_id must be non-empty string")
            if not isinstance(agent, dict):
                raise ValueError(f"[AGENTS] '{agent_id}' must be object")

        # Keep full structure (version + agents) as returned payload
        return {"version": data.get("version"), "agents": agents}

    return _load_cached("agents", _load)


# ============================================================
# CEO IDENTITY PACK (READ-ONLY, FAIL-SOFT)
# ============================================================


def load_ceo_identity_pack() -> Dict[str, Any]:
    """
    Returns a best-effort "identity pack" for CEO Advisor context.

    - Fail-soft: each section attempted independently.
    - available == False only if both identity and kernel are missing.
    - errors list contains per-section errors.
    """
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

    def _try(label: str, fn: Callable[[], Dict[str, Any]]) -> None:
        try:
            pack[label] = fn()
        except Exception as e:  # noqa: BLE001
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
