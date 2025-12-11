import os
import json
from datetime import datetime
from services.identity_loader import load_adnan_identity


def load_json_file(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"State file not found: {path}")

    # FIX: UTF-8 BOM safe loading
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def resolve_path(filename: str) -> str:
    """
    Ensures correct path resolution inside:
    - Local development
    - Docker containers
    - Render deployment
    """

    # Location of this file: /app/services/adnan_state_service.py
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Project root: /app/
    project_root = os.path.abspath(os.path.join(current_dir, ".."))

    # identity folder: /app/identity/
    identity_dir = os.path.join(project_root, "identity")

    return os.path.join(identity_dir, filename)


# ================================================================
# LOAD FULL STATE FILE (USED BY ORCHESTRATOR + GATEWAY)
# ================================================================
def load_state():
    """
    Loads a full persisted Adnan.AI state from identity folder.
    Required by:
        - Context Orchestrator
        - Gateway Server
    """
    state_path = resolve_path("adnan_ai_state.json")
    return load_json_file(state_path)


# ================================================================
# MINIMAL RUNTIME STATE (USED BY OTHER MODULES)
# ================================================================
def get_adnan_state():
    """
    Returns safe, minimal, dynamic runtime state.
    Does not modify or depend on persistent state storage.
    """
    return {
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "identity": load_adnan_identity()
    }
