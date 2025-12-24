import json
import os
from typing import Any, Dict

# ================================================================
# INTERNAL HELPERS
# ================================================================


def load_json_file(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Mode file not found: {path}")

    # UTF-8 BOM safe
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Mode file root must be a JSON object: {path}")

    return data


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
    current_dir = os.path.dirname(os.path.abspath(__file__))  # /app/services
    project_root = os.path.abspath(os.path.join(current_dir, ".."))  # /app
    identity_dir = os.path.join(project_root, "identity")  # /app/identity
    return os.path.join(identity_dir, filename)


# ================================================================
# CANONICAL MODE LOAD / SAVE
# ================================================================


def load_mode() -> Dict[str, Any]:
    """
    Loads persisted Adnan.AI operating mode.
    Canonical file: identity/mode.json

    NOTE:
    - This is a local file read.
    - It is safe for READ-only contexts (CEO Advisory).
    """
    path = resolve_path("mode.json")
    return load_json_file(path)


def save_mode(mode: Dict[str, Any]) -> None:
    """
    Persists Adnan.AI operating mode.

    NOTE:
    - This is a local file write.
    - It must NOT be called from READ-only advisory endpoints.
    - It is used only by explicit system services (e.g., degradation/recovery).
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
            "description": mode.get("description", "Evolia Operational Mode"),
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
