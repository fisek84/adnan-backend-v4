import os
import json
from services.identity_loader import load_adnan_mode


def load_json_file(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Mode file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_path(filename: str) -> str:
    """
    Resolves correct identity directory path across:
    - Local dev
    - Docker
    - Render
    """

    # Location of this file: /app/services/adnan_mode_service.py
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Project root: /app/
    project_root = os.path.abspath(os.path.join(current_dir, ".."))

    # Identity folder: /app/identity/
    identity_dir = os.path.join(project_root, "identity")

    return os.path.join(identity_dir, filename)


# ================================================================
# MAIN MODE LOADER (USED BY ORCHESTRATOR + GATEWAY)
# ================================================================
def load_mode():
    """
    Loads persisted Adnan.AI operating mode.
    Example file: identity/adnan_ai_mode.json
    """
    path = resolve_path("adnan_ai_mode.json")
    return load_json_file(path)


# ================================================================
# MINIMAL RUNTIME MODE
# ================================================================
def get_adnan_mode():
    """
    Legacy compatibility — returns current mode in a safe form.
    Not used by orchestrator, but kept for backward compatibility.
    """
    try:
        mode = load_adnan_mode()
        return {
            "active_mode": mode.get("active_mode", "ceo"),
            "description": mode.get("description", "Evolia Operational Mode")
        }
    except Exception:
        return {
            "active_mode": "ceo",
            "description": "Default Mode (fallback)"
        }


# ================================================================
# RUNTIME ACCESSOR
# ================================================================
def get_runtime_mode():
    """
    Returns safe mode snapshot for UI or runtime modules.
    """
    return get_adnan_mode()
