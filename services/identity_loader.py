import os
import json
from typing import Dict, Any


# ============================================================
# CORE JSON LOADER (UTF-8 BOM SAFE)
# ============================================================

def load_json_file(path: str) -> Dict[str, Any]:
    """
    Loads JSON file safely.
    - Strips UTF-8 BOM if present
    - Fails fast on invalid JSON
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"[IDENTITY] File not found: {path}")

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"[IDENTITY] Invalid JSON in {path}: {e}") from e


# ============================================================
# PATH RESOLUTION (ENV-AGNOSTIC)
# ============================================================

def resolve_path(filename: str) -> str:
    """
    Resolves identity directory path regardless of runtime:
    - local
    - docker
    - render
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))   # /app/services
    project_root = os.path.abspath(os.path.join(current_dir, ".."))  # /app
    identity_dir = os.path.join(project_root, "identity")       # /app/identity
    return os.path.join(identity_dir, filename)


# ============================================================
# VALIDATION (STRICT — FAIL FAST)
# ============================================================

def validate_identity_payload(payload: Dict[str, Any], required_keys: list, name: str):
    if not isinstance(payload, dict):
        raise ValueError(f"[IDENTITY] {name} must be a JSON object")

    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise ValueError(
            f"[IDENTITY] {name} missing required keys: {missing}"
        )


def validate_agent_definition(agent_id: str, agent: Dict[str, Any]):
    required_keys = ["type", "capabilities", "enabled"]

    missing = [k for k in required_keys if k not in agent]
    if missing:
        raise ValueError(
            f"[AGENTS] Agent '{agent_id}' missing required keys: {missing}"
        )

    if not isinstance(agent["capabilities"], list):
        raise ValueError(
            f"[AGENTS] Agent '{agent_id}' capabilities must be a list"
        )

    if not isinstance(agent["enabled"], bool):
        raise ValueError(
            f"[AGENTS] Agent '{agent_id}' enabled must be boolean"
        )


# ============================================================
# LOADERS (CANONICAL — SOURCE OF TRUTH)
# ============================================================

def load_adnan_identity():
    data = load_json_file(resolve_path("identity.json"))
    validate_identity_payload(
        data,
        required_keys=["name", "role", "version"],
        name="identity.json"
    )
    return data


def load_adnan_memory():
    data = load_json_file(resolve_path("memory.json"))
    validate_identity_payload(
        data,
        required_keys=["short_term", "long_term"],
        name="memory.json"
    )
    return data


def load_adnan_kernel():
    data = load_json_file(resolve_path("kernel.json"))
    validate_identity_payload(
        data,
        required_keys=["principles", "constraints"],
        name="kernel.json"
    )
    return data


def load_adnan_static_memory():
    data = load_json_file(resolve_path("static_memory.json"))
    validate_identity_payload(
        data,
        required_keys=["facts"],
        name="static_memory.json"
    )
    return data


def load_adnan_mode():
    data = load_json_file(resolve_path("mode.json"))
    validate_identity_payload(
        data,
        required_keys=["current_mode"],
        name="mode.json"
    )
    return data


def load_adnan_state():
    data = load_json_file(resolve_path("state.json"))
    validate_identity_payload(
        data,
        required_keys=["status"],
        name="state.json"
    )
    return data


def load_decision_engine_config():
    data = load_json_file(resolve_path("decision_engine.json"))
    validate_identity_payload(
        data,
        required_keys=["strategy"],
        name="decision_engine.json"
    )
    return data


# ============================================================
# AGENT IDENTITY & CAPABILITIES (FAZA 7 — KORAK 1)
# ============================================================

def load_agents_identity() -> Dict[str, Dict[str, Any]]:
    """
    Loads agent identity & capability definitions from identity/agents.json.
    Passive, read-only, no execution.
    """
    data = load_json_file(resolve_path("agents.json"))

    if not isinstance(data, dict):
        raise ValueError("[AGENTS] agents.json must be a JSON object")

    for agent_id, agent in data.items():
        validate_agent_definition(agent_id, agent)

    return data


# ============================================================
# BACKWARD COMPATIBILITY (DO NOT REMOVE)
# ============================================================

def load_identity():
    return load_adnan_identity()


def load_mode():
    return load_adnan_mode()


def load_state():
    return load_adnan_state()
