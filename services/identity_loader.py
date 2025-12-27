import json
import os
from typing import Any, Dict

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
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"[IDENTITY] JSON root must be an object: {path}")
        return data
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
    current_dir = os.path.dirname(os.path.abspath(__file__))  # /app/services
    project_root = os.path.abspath(os.path.join(current_dir, ".."))  # /app
    identity_dir = os.path.join(project_root, "identity")  # /app/identity
    return os.path.join(identity_dir, filename)


# ============================================================
# VALIDATION (STRICT — FAIL FAST)
# ============================================================


def validate_identity_payload(
    payload: Dict[str, Any], required_keys: list, name: str
) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"[IDENTITY] {name} must be a JSON object")
    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise ValueError(f"[IDENTITY] {name} missing required keys: {missing}")


def validate_agent_definition(agent_id: str, agent: Dict[str, Any]) -> None:
    required_keys = ["type", "capabilities", "enabled"]
    missing = [k for k in required_keys if k not in agent]
    if missing:
        raise ValueError(
            f"[AGENTS] Agent '{agent_id}' missing required keys: {missing}"
        )
    if not isinstance(agent["capabilities"], list):
        raise ValueError(f"[AGENTS] Agent '{agent_id}' capabilities must be a list")
    if not isinstance(agent["enabled"], bool):
        raise ValueError(f"[AGENTS] Agent '{agent_id}' enabled must be boolean")


# ============================================================
# LOADERS (CANONICAL — SOURCE OF TRUTH)
# ============================================================


def load_adnan_identity() -> Dict[str, Any]:
    data = load_json_file(resolve_path("identity.json"))
    validate_identity_payload(
        data, required_keys=["name", "role", "version"], name="identity.json"
    )
    return data


def load_adnan_memory() -> Dict[str, Any]:
    data = load_json_file(resolve_path("memory.json"))
    validate_identity_payload(
        data, required_keys=["short_term", "long_term"], name="memory.json"
    )
    return data


def load_adnan_kernel() -> Dict[str, Any]:
    data = load_json_file(resolve_path("kernel.json"))
    validate_identity_payload(
        data, required_keys=["principles", "constraints"], name="kernel.json"
    )
    return data


def load_adnan_static_memory() -> Dict[str, Any]:
    data = load_json_file(resolve_path("static_memory.json"))
    validate_identity_payload(data, required_keys=["facts"], name="static_memory.json")
    return data


def load_adnan_mode() -> Dict[str, Any]:
    data = load_json_file(resolve_path("mode.json"))
    validate_identity_payload(data, required_keys=["current_mode"], name="mode.json")
    return data


def load_adnan_state() -> Dict[str, Any]:
    data = load_json_file(resolve_path("state.json"))
    validate_identity_payload(data, required_keys=["status"], name="state.json")
    return data


def load_decision_engine_config() -> Dict[str, Any]:
    data = load_json_file(resolve_path("decision_engine.json"))
    validate_identity_payload(
        data, required_keys=["strategy"], name="decision_engine.json"
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
    for agent_id, agent in data.items():
        if not isinstance(agent, dict):
            raise ValueError(f"[AGENTS] Agent '{agent_id}' entry must be a JSON object")
        validate_agent_definition(agent_id, agent)
    return data


# ============================================================
# CEO IDENTITY PACK (READ-ONLY, ADVISORY-READY)
# ============================================================


def load_ceo_identity_pack() -> Dict[str, Any]:
    """
    Builds a compact, advisory-ready 'identity pack' for CEO Advisory.
    Why:
    - CEO advisory needs 'CEO logic / philosophy / principles' in a stable shape.
    - Keep it READ-only and deterministic.
    - Fail-soft: if some optional files are missing, return what exists.
    Sources (all optional except identity.json + kernel.json in most setups):
    - identity.json (name/role/version)
    - kernel.json (principles/constraints)
    - decision_engine.json (strategy)
    - static_memory.json (facts)
    - memory.json (short_term/long_term)
    - agents.json (capabilities map)
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

    # If even core identity/kernel are missing, mark as not available
    if pack.get("identity") is None and pack.get("kernel") is None:
        pack["available"] = False

    return pack


# ============================================================
# BACKWARD COMPATIBILITY (DO NOT REMOVE)
# ============================================================


def load_identity() -> Dict[str, Any]:
    return load_adnan_identity()


def load_mode() -> Dict[str, Any]:
    return load_adnan_mode()


def load_state() -> Dict[str, Any]:
    return load_adnan_state()
