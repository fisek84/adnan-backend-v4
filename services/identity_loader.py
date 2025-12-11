import os
import json


def load_json_file(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Identity file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_path(filename: str) -> str:
    """
    Always resolves correct identity directory regardless of environment:
    - Local development
    - Docker container
    - Render deployment
    """

    # Location of this file: /app/services/identity_loader.py
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Project root: /app/
    project_root = os.path.abspath(os.path.join(current_dir, ".."))

    # Identity folder inside project root
    identity_dir = os.path.join(project_root, "identity")

    # Full path to requested identity file
    return os.path.join(identity_dir, filename)


def load_adnan_identity():
    identity_path = resolve_path("adnan_ai_identity.json")
    return load_json_file(identity_path)


def load_adnan_memory():
    memory_path = resolve_path("adnan_ai_memory.json")
    return load_json_file(memory_path)


def load_adnan_kernel():
    kernel_path = resolve_path("adnan_ai_kernel.json")
    return load_json_file(kernel_path)


def load_adnan_static_memory():
    static_path = resolve_path("adnan_ai_static_memory.json")
    return load_json_file(static_path)


def load_adnan_mode():
    mode_path = resolve_path("adnan_ai_mode.json")
    return load_json_file(mode_path)


def load_adnan_state():
    state_path = resolve_path("adnan_ai_state.json")
    return load_json_file(state_path)


# ============================================================
# BACKWARD-COMPATIBLE WRAPPERS FOR GATEWAY IMPORTS
# ============================================================

def load_identity():
    """Compatibility wrapper for gateway_server.py"""
    return load_adnan_identity()


def load_mode():
    """Compatibility wrapper for gateway_server.py"""
    return load_adnan_mode()


def load_state():
    """Compatibility wrapper for gateway_server.py"""
    return load_adnan_state()
