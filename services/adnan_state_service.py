import json
import os
from datetime import datetime
from typing import Any, Dict


def load_json_file(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"State file not found: {path}")

    # UTF-8 BOM safe
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"State file root must be a JSON object: {path}")

    return data


def resolve_path(filename: str) -> str:
    """
    Ensures correct path resolution inside:
    - Local development
    - Docker containers
    - Render deployment
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))  # /app/services
    project_root = os.path.abspath(os.path.join(current_dir, ".."))  # /app
    identity_dir = os.path.join(project_root, "identity")  # /app/identity
    return os.path.join(identity_dir, filename)


# ================================================================
# LOAD FULL STATE FILE (USED BY ORCHESTRATOR + GATEWAY)
# ================================================================


def load_state() -> Dict[str, Any]:
    """
    Loads a full persisted Adnan.AI state from identity folder.
    Required by:
      - Context Orchestrator
      - Gateway Server

    NOTE:
    - This is a local file read.
    - Safe for READ-only contexts (CEO Advisory).
    """
    state_path = resolve_path("state.json")
    return load_json_file(state_path)


# ================================================================
# MINIMAL RUNTIME STATE (USED BY OTHER MODULES)
# ================================================================


def get_adnan_state() -> Dict[str, Any]:
    """
    Returns safe, minimal, dynamic runtime state.
    Does not modify or depend on persistent state storage.
    """
    try:
        from services.identity_loader import (
            load_adnan_identity,
        )  # local import to avoid cycles
    except Exception:
        load_adnan_identity = None

    identity = None
    if load_adnan_identity:
        try:
            identity = load_adnan_identity()
        except Exception:
            identity = None

    return {
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "identity": identity or {"available": False},
    }
