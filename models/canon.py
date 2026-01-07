# models/canon.py
# Single source of truth for canon constants + small helpers.

from __future__ import annotations

from typing import Any, Dict, Optional

# CANON: wrapper intent used across chat -> proposal -> promotion -> approval pipeline
PROPOSAL_WRAPPER_INTENT = "ceo.command.propose"


def extract_prompt_from_args_or_params(d: Any) -> Optional[str]:
    """
    Accept both shapes:
      - {"args": {"prompt": "..."}}
      - {"params": {"prompt": "..."}}

    Returns stripped prompt or None.
    """
    if not isinstance(d, dict):
        return None

    for key in ("args", "params"):
        v = d.get(key)
        if isinstance(v, dict):
            p = v.get("prompt")
            if isinstance(p, str) and p.strip():
                return p.strip()

    return None


def ensure_prompt_in_params(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    For execute/raw input: ensure params.prompt exists for wrapper calls,
    using args.prompt if needed.

    This is intentionally minimal and side-effect free beyond normalizing
    the passed-in dict (same reference).
    """
    if not isinstance(payload, dict):
        return payload

    params = payload.get("params")
    if not isinstance(params, dict):
        params = {}
        payload["params"] = params

    # If already present -> normalize whitespace
    p0 = params.get("prompt")
    if isinstance(p0, str) and p0.strip():
        params["prompt"] = p0.strip()
        return payload

    # Back-compat: accept args.prompt and promote into params.prompt
    args = payload.get("args")
    if isinstance(args, dict):
        p1 = args.get("prompt")
        if isinstance(p1, str) and p1.strip():
            params["prompt"] = p1.strip()

    return payload
