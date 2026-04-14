# services/notion_ops_state.py
"""services.notion_ops_state

NOTION OPS ARMED STATE - SINGLE SOURCE OF TRUTH (SSOT)

BE-301:
- Canonical key is authenticated principal.sub (principal-based).
- Some legacy flows still pass a session_id; treat the input as a generic subject key.
- Persisted SSOT via services.notion_armed_store (no parallel in-memory truth).
- Deterministic expiry/revoke semantics.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from services import notion_armed_store


async def _to_thread(func, *args, **kwargs):
    """Run blocking store IO without stalling the event loop."""

    try:
        to_thread = asyncio.to_thread  # py>=3.9
    except AttributeError:  # pragma: no cover
        loop = asyncio.get_running_loop()

        def _call():
            return func(*args, **kwargs)

        return await loop.run_in_executor(None, _call)

    return await to_thread(func, *args, **kwargs)


def resolve_state_subject(
    *,
    session_id: Any = None,
    metadata: Any = None,
    identity_pack: Any = None,
) -> str | None:
    """Resolve the canonical Notion Ops state key for request-time checks.

    Preference order:
    1. verified/explicit principal-like fields in metadata
    2. identity pack subject
    3. browser-session session_id fallback

    This mirrors runtime behavior where authenticated flows use principal.sub,
    while browser-session CEO Console flows use session_id as the actor key.
    """

    if isinstance(metadata, dict):
        for key in ("principal_sub", "sub", "actor_sub", "approved_by_sub"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    if isinstance(identity_pack, dict):
        payload = (
            identity_pack.get("payload")
            if isinstance(identity_pack.get("payload"), dict)
            else {}
        )
        for value in (payload.get("sub"), identity_pack.get("sub")):
            if isinstance(value, str) and value.strip():
                return value.strip()

    if isinstance(session_id, str) and session_id.strip():
        return session_id.strip()

    if isinstance(metadata, dict):
        for key in ("session_id", "sessionId"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return None


def _arm_ttl_seconds() -> int:
    raw = (os.getenv("NOTION_OPS_ARM_TTL_SECONDS", "3600") or "").strip()
    try:
        v = int(raw)
    except Exception:
        v = 3600
    return v if v > 0 else 3600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    """Returns current UTC timestamp in ISO format."""
    return _utcnow().isoformat()


def _parse_iso(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _apply_expiry_in_place(st: Dict[str, Any]) -> None:
    """Mutates st deterministically based on UTC now and expires_at."""
    if not isinstance(st, dict):
        return
    if st.get("armed") is not True:
        return

    expires_at = _parse_iso(st.get("expires_at"))
    if expires_at is None:
        return

    now = _utcnow()
    # Expired => treat as disarmed and mark expiry once.
    if now >= expires_at:
        st["armed"] = False
        st.setdefault("expired_at", now.isoformat())
        st["status"] = "expired"
        st["armed_at"] = None
        st["expires_at"] = None


async def set_armed(
    principal_sub: str, armed: bool, *, prompt: str = ""
) -> Dict[str, Any]:
    """
    Set principal state to armed/unarmed.

    Args:
        principal_sub: Canonical principal identifier (principal.sub)
        armed: True to arm, False to disarm
        prompt: Optional prompt that triggered the state change

    Returns:
        Dict containing the updated principal state
    """
    principal_sub = (principal_sub or "").strip()
    if not principal_sub:
        raise ValueError("principal_sub must be a non-empty string")

    now_iso = _now_iso()
    st: Dict[str, Any] = {}

    if bool(armed) is True:
        ttl = _arm_ttl_seconds()
        st["armed"] = True
        st["status"] = "armed"
        st["armed_at"] = now_iso
        st["expires_at"] = (_utcnow() + timedelta(seconds=ttl)).isoformat()
        st["revoked_at"] = None
        st["expired_at"] = None
    else:
        st["armed"] = False
        st["status"] = "disarmed"
        st["armed_at"] = None
        st["expires_at"] = None
        st["revoked_at"] = now_iso
        st["expired_at"] = None

    st["last_prompt_id"] = None
    st["last_prompt"] = (prompt or "").strip() or None
    st["last_toggled_at"] = now_iso

    # Persist: single SSOT used by toggle endpoint and execution gating.
    out = await _to_thread(notion_armed_store.set, principal_sub, st)
    return dict(out)


async def get_state(principal_sub: str) -> Dict[str, Any]:
    """
    Get the current armed state for a principal.

    Args:
        principal_sub: Canonical principal identifier (principal.sub)

    Returns:
        Dict containing principal state (armed, armed_at, etc.)
        Returns default state with armed=False if principal doesn't exist
    """
    principal_sub = (principal_sub or "").strip()
    if not principal_sub:
        raise ValueError("principal_sub must be a non-empty string")

    st = await _to_thread(notion_armed_store.get, principal_sub)

    # Normalize for legacy callers.
    if "armed" not in st:
        st["armed"] = False
    if "status" not in st:
        st["status"] = "disarmed" if st.get("armed") is not True else "armed"
    if "armed_at" not in st:
        st["armed_at"] = None
    if "expires_at" not in st:
        st["expires_at"] = None
    if "revoked_at" not in st:
        st["revoked_at"] = None
    if "expired_at" not in st:
        st["expired_at"] = None

    return dict(st)


async def is_armed(principal_sub: str) -> bool:
    """
    Quick check if a principal is armed.

    Args:
        principal_sub: Canonical principal identifier (principal.sub)

    Returns:
        True if armed, False otherwise
    """
    state = await get_state(principal_sub)
    return bool(state.get("armed") is True)
