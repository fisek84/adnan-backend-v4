import os
import json
from typing import Dict, Any

# ================================================================
# INTERNAL HELPERS
# ================================================================

def load_json_file(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Mode file not found: {path}")

    # UTF-8 BOM safe
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_json_file(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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
# CANONICAL MODE LOAD / SAVE
# ================================================================

def load_mode() -> Dict[str, Any]:
    """
    Loads persisted Adnan.AI operating mode.
    Canonical file: identity/mode.json
    """
    path = resolve_path("mode.json")
    return load_json_file(path)


def save_mode(mode: Dict[str, Any]) -> None:
    """
    Persists Adnan.AI operating mode.
    Used by:
    - AutoDegradationService
    - future AutoRecoveryService
    """
    path = resolve_path("mode.json")
    save_json_file(path, mode)


# ================================================================
# LEGACY / BACKWARD COMPATIBILITY
# ================================================================

def get_adnan_mode() -> Dict[str, Any]:
    """
    Legacy compatibility accessor.

    Returns a SAFE subset for UI / older modules.
    """
    try:
        mode = load_mode()
        return {
            "active_mode": mode.get("current_mode", "operational"),
            "description": mode.get(
                "description",
                "Evolia Operational Mode"
            ),
        }
    except Exception:
        return {
            "active_mode": "operational",
            "description": "Default Mode (fallback)",
        }


def get_runtime_mode() -> Dict[str, Any]:
    """
    Returns runtime-safe mode snapshot.
    """
    return get_adnan_mode()
