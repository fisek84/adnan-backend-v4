"""
AGENT HEALTH SERVICE — CANONICAL (FAZA 10)

Uloga:
- centralni HEALTH MONITOR za agente
- prati liveness / readiness / heartbeat
- NEMA execution
- NEMA routing
- NEMA governance / approval
- služi AgentRouter-u i LoadBalancer-u kao SIGNALNI sloj
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import os
import threading


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc_iso(v: Optional[str]) -> Optional[datetime]:
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resolve_heartbeat_ttl_seconds() -> int:
    """
    TTL after which agent without heartbeat is considered unhealthy.
    Env priority:
      AGENT_HEALTH_TTL_SECONDS
      AGENT_HEALTH_TTL_MINUTES
    Default: 120s
    """
    raw_s = (os.getenv("AGENT_HEALTH_TTL_SECONDS") or "").strip()
    raw_m = (os.getenv("AGENT_HEALTH_TTL_MINUTES") or "").strip()

    try:
        if raw_s:
            return max(1, int(raw_s))
    except Exception:
        pass

    try:
        if raw_m:
            return max(1, int(raw_m)) * 60
    except Exception:
        pass

    return 120


_HEARTBEAT_TTL_SECONDS = _resolve_heartbeat_ttl_seconds()


class AgentHealthService:
    """
    CANONICAL AGENT HEALTH SERVICE (THREAD-SAFE)

    HARD GUARANTEES:
    - no deadlocks (single lock discipline)
    - heartbeat TTL enforcement
    - read-only snapshots
    """

    def __init__(self):
        self._health: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # =========================================================
    # INTERNAL (LOCKED)
    # =========================================================
    def _ensure_locked(self, agent_name: str) -> Dict[str, Any]:
        if agent_name not in self._health:
            self._health[agent_name] = {
                "alive": False,
                "status": "unknown",  # healthy | degraded | unhealthy | unknown
                "last_heartbeat": None,
                "reason": None,
            }
        return self._health[agent_name]

    def _apply_ttl_locked(self, agent_name: str, state: Dict[str, Any]) -> None:
        last = _parse_utc_iso(state.get("last_heartbeat"))
        if not last:
            return
        now = datetime.now(timezone.utc)
        if now - last > timedelta(seconds=_HEARTBEAT_TTL_SECONDS):
            state["alive"] = False
            state["status"] = "unhealthy"
            state.setdefault("reason", "heartbeat_ttl_expired")

    # =========================================================
    # PUBLIC API
    # =========================================================
    def register_agent(self, agent_name: str) -> None:
        with self._lock:
            self._ensure_locked(agent_name)

    def mark_heartbeat(self, agent_name: str) -> None:
        with self._lock:
            state = self._ensure_locked(agent_name)
            state["alive"] = True
            state["status"] = "healthy"
            state["last_heartbeat"] = _utc_now_iso()
            state.pop("reason", None)

    def mark_degraded(self, agent_name: str, reason: Optional[str] = None) -> None:
        with self._lock:
            state = self._ensure_locked(agent_name)
            state["status"] = "degraded"
            state["alive"] = True
            state["last_heartbeat"] = _utc_now_iso()
            if reason:
                state["reason"] = reason

    def mark_unhealthy(self, agent_name: str, reason: Optional[str] = None) -> None:
        with self._lock:
            state = self._ensure_locked(agent_name)
            state["alive"] = False
            state["status"] = "unhealthy"
            state["last_heartbeat"] = _utc_now_iso()
            if reason:
                state["reason"] = reason

    def is_healthy(self, agent_name: str) -> bool:
        with self._lock:
            state = self._health.get(agent_name)
            if not state:
                return False
            self._apply_ttl_locked(agent_name, state)
            return state.get("status") == "healthy"

    # =========================================================
    # SNAPSHOT (READ-ONLY)
    # =========================================================
    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            out: Dict[str, Dict[str, Any]] = {}
            for agent, s in self._health.items():
                self._apply_ttl_locked(agent, s)
                out[agent] = {
                    "alive": s.get("alive"),
                    "status": s.get("status"),
                    "last_heartbeat": s.get("last_heartbeat"),
                    "reason": s.get("reason"),
                    "read_only": True,
                }
            return out
