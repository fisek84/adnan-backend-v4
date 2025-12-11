import os
import json


def load_json_file(path: str):
    """
    Loads JSON files and automatically strips UTF-8 BOM if present.
    Prevents JSONDecodeError: Unexpected UTF-8 BOM.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Identity file not found: {path}")

    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def resolve_path(filename: str) -> str:
    """
    Resolves correct identity directory regardless of:
    - Local development
    - Docker container
    - Render deployment
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))   # /app/services/
    project_root = os.path.abspath(os.path.join(current_dir, ".."))  # /app/
    identity_dir = os.path.join(project_root, "identity")       # /app/identity
    return os.path.join(identity_dir, filename)


# ============================================================
# LOADERS FOR REAL FILES (WITHOUT adnan_ai_ PREFIX)
# ============================================================

def load_adnan_identity():
    return load_json_file(resolve_path("identity.json"))


def load_adnan_memory():
    return load_json_file(resolve_path("memory.json"))


def load_adnan_kernel():
    return load_json_file(resolve_path("kernel.json"))


def load_adnan_static_memory():
    return load_json_file(resolve_path("static_memory.json"))


def load_adnan_mode():
    return load_json_file(resolve_path("mode.json"))


def load_adnan_state():
    return load_json_file(resolve_path("state.json"))


# Optional — if your engine needs this
def load_decision_engine_config():
    return load_json_file(resolve_path("decision_engine.json"))


# ============================================================
# BACKWARD COMPATIBILITY FOR gateway_server.py
# ============================================================

def load_identity():
    return load_adnan_identity()

def load_mode():
    return load_adnan_mode()

def load_state():
    return load_adnan_state()
