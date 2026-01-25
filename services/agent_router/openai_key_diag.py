from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Optional


def _sha256_12(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def _read_dotenv_value(dotenv_path: Path, key: str) -> Optional[str]:
    """Read a single key from a .env file without requiring python-dotenv.

    Never returns surrounding quotes.
    """

    try:
        raw = dotenv_path.read_text(encoding="utf-8")
    except Exception:
        return None

    target = f"{key}="
    for line in raw.splitlines():
        ln = line.strip()
        if not ln or ln.startswith("#"):
            continue
        if not ln.startswith(target):
            continue
        v = ln[len(target) :].strip()
        if (v.startswith('"') and v.endswith('"')) or (
            v.startswith("'") and v.endswith("'")
        ):
            v = v[1:-1]
        return v

    return None


def get_openai_key_diag(*, dotenv_path: Optional[Path] = None) -> Dict[str, Any]:
    """Return non-secret, stable OpenAI key diagnostics.

    This does NOT log or return the raw key.

    Keys:
      present: bool
      len: int
      prefix: str
      fingerprint: str (sha256[:12])
      source: one of {"env","dotenv","config","none"}
      mode: OPENAI_API_MODE
      base_url: configured base url (env), if any
    """

    # Process config
    mode = (os.getenv("OPENAI_API_MODE") or "").strip() or "(unset)"
    base_url = (
        (os.getenv("OPENAI_BASE_URL") or "").strip()
        or (os.getenv("OPENAI_API_BASE") or "").strip()
        or (os.getenv("OPENAI_API_BASE_URL") or "").strip()
        or None
    )

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    present = bool(api_key)

    prefix = api_key[:7] if present else ""
    fp = _sha256_12(api_key) if present else ""

    # Best-effort source attribution.
    # Note: once loaded into os.environ, Python cannot reliably know whether it came
    # from the parent shell vs python-dotenv. We infer by comparing to repo-root .env.
    source = "none"
    if present:
        source = "env"

        try:
            if dotenv_path is None:
                # services/agent_router/* -> repo root
                dotenv_path = Path(__file__).resolve().parents[2] / ".env"

            dotenv_val = _read_dotenv_value(dotenv_path, "OPENAI_API_KEY")
            if isinstance(dotenv_val, str) and dotenv_val.strip() == api_key:
                source = "dotenv"
        except Exception:
            source = source

    return {
        "present": bool(present),
        "len": int(len(api_key)) if present else 0,
        "prefix": prefix,
        "fingerprint": fp,
        "source": source,
        "mode": mode,
        "base_url": base_url,
    }
