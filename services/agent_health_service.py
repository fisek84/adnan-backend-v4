"""
AGENT HEALTH SERVICE — CANONICAL (FAZA 10)

Uloga:
- centralni HEALTH MONITOR za agente
- prati liveness / readiness / heartbeat
- NEMA execution
- NEMA routing
- NEMA governance / approval
- služi AgentRouter-u i LoadBalancer-u kao SIGNALNI sloj

AgentHealthService ≠ AgentRegistryService
AgentHealthService ≠ AgentLoadBalancerService
"""

from typing import Dict, Any, Optional
from datetime import datetime
import threading


class AgentHealthService:
    def __init__(self):
        # runtime health state po agentu
        self._health: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # =========================================================
    # INTERNAL
    # =========================================================
    def _ensure(self, agent_name: str) -> Dict[str, Any]:
        with self._lock:
            if agent_name not in self._health:
                self._health[agent_name] = {
                    "alive": False,
                    "last_heartbeat": None,
                    "status": "unknown",  # healthy | degraded | unhealthy | unknown
                }
            return self._health[agent_name]

    # =========================================================
    # PUBLIC API
    # =========================================================
    def register_agent(self, agent_name: str) -> None:
        self._ensure(agent_name)

    def mark_heartbeat(self, agent_name: str) -> None:
        with self._lock:
            state = self._ensure(agent_name)
            state["alive"] = True
            state["status"] = "healthy"
            state["last_heartbeat"] = datetime.utcnow().isoformat()

    def mark_degraded(self, agent_name: str, reason: Optional[str] = None) -> None:
        with self._lock:
            state = self._ensure(agent_name)
            state["status"] = "degraded"
            state["last_heartbeat"] = datetime.utcnow().isoformat()
            if reason:
                state["reason"] = reason

    def mark_unhealthy(self, agent_name: str, reason: Optional[str] = None) -> None:
        with self._lock:
            state = self._ensure(agent_name)
            state["alive"] = False
            state["status"] = "unhealthy"
            state["last_heartbeat"] = datetime.utcnow().isoformat()
            if reason:
                state["reason"] = reason

    def is_healthy(self, agent_name: str) -> bool:
        with self._lock:
            state = self._health.get(agent_name)
            if not state:
                return False
            return state.get("status") == "healthy"

    # =========================================================
    # SNAPSHOT (READ-ONLY)
    # =========================================================
    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                agent: {
                    "alive": s["alive"],
                    "status": s["status"],
                    "last_heartbeat": s["last_heartbeat"],
                    "read_only": True,
                }
                for agent, s in self._health.items()
            }
