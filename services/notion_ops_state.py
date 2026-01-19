# services/notion_ops_state.py
"""
NOTION OPS SESSION STATE - SINGLE SOURCE OF TRUTH (SSOT)

This module provides a centralized, thread-safe storage for Notion Ops
armed/disarmed state per session.

PHASE 6: Notion Ops ARMED Gate
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict


# ------------------------------
# NOTION OPS SESSION STATE (SSOT)
# ------------------------------
# Per-session, in-memory (no new deps).
# Default armed=False.
# Keyed by session_id.
_NOTION_OPS_SESSIONS: Dict[str, Dict[str, Any]] = {}
_NOTION_OPS_LOCK = asyncio.Lock()


def _now_iso() -> str:
    """Returns current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


async def set_armed(
    session_id: str, armed: bool, *, prompt: str = ""
) -> Dict[str, Any]:
    """
    Set session state to armed/unarmed.

    Args:
        session_id: The session identifier
        armed: True to arm, False to disarm
        prompt: Optional prompt that triggered the state change

    Returns:
        Dict containing the updated session state
    """
    async with _NOTION_OPS_LOCK:
        st = _NOTION_OPS_SESSIONS.get(session_id) or {}
        st["armed"] = bool(armed)
        st["armed_at"] = _now_iso() if armed else None
        st["last_prompt_id"] = None
        st["last_toggled_at"] = _now_iso()
        _NOTION_OPS_SESSIONS[session_id] = st
        return dict(st)


async def get_state(session_id: str) -> Dict[str, Any]:
    """
    Get the current armed state for a session.

    Args:
        session_id: The session identifier

    Returns:
        Dict containing session state (armed, armed_at, etc.)
        Returns default state with armed=False if session doesn't exist
    """
    async with _NOTION_OPS_LOCK:
        st = _NOTION_OPS_SESSIONS.get(session_id) or {
            "armed": False,
            "armed_at": None,
        }
        if "armed" not in st:
            st["armed"] = False
        if "armed_at" not in st:
            st["armed_at"] = None
        return dict(st)


async def is_armed(session_id: str) -> bool:
    """
    Quick check if a session is armed.

    Args:
        session_id: The session identifier

    Returns:
        True if armed, False otherwise
    """
    state = await get_state(session_id)
    return bool(state.get("armed") is True)
