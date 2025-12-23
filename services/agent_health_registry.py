# services/agent_health_registry.py

from typing import Dict, Any
from datetime import datetime
from threading import Lock
from copy import deepcopy


class AgentHealthRegistry:
    """
    AgentHealthRegistry — FAZA 10 (AGENT SPECIALIZATION)

    Canonical rules:
    - Agents declared in identity are considered "available" at boot.
    - Health registry tracks ONLY health signals (alive / last_seen / error_count).
    - No execution, no restart logic, no decisions.
    - READ-ONLY for execution layer.
    """

    def __init__(self):
        self._lock = Lock()
        self._registry: Dict[str, Dict[str, Any]] = {}

    # -------------------------------------------------
    # REGISTRATION
    # -------------------------------------------------
    def register_agent(self, agent_id: str, *, alive: bool = True):
        """
        Registers agent in health registry.

        Canonical rule:
        - identity-defined agents are treated as alive at startup
        """
        if not agent_id:
            raise ValueError("agent_id is required")

        with self._lock:
            now = datetime.utcnow().isoformat()
            if agent_id not in self._registry:
                self._registry[agent_id] = {
                    "alive": bool(alive),
                    "last_seen": now if alive else None,
                    "error_count": 0,
                }
            else:
                self._registry[agent_id]["alive"] = bool(alive)
                if alive:
                    self._registry[agent_id]["last_seen"] = now

    # -------------------------------------------------
    # HEARTBEAT / STATUS UPDATE
    # -------------------------------------------------
    def mark_alive(self, agent_id: str):
        if not agent_id:
            return

        with self._lock:
            self._ensure_agent(agent_id)
            self._registry[agent_id]["alive"] = True
            self._registry[agent_id]["last_seen"] = datetime.utcnow().isoformat()

    def mark_down(self, agent_id: str):
        if not agent_id:
            return

        with self._lock:
            self._ensure_agent(agent_id)
            self._registry[agent_id]["alive"] = False

    def record_error(self, agent_id: str):
        if not agent_id:
            return

        with self._lock:
            self._ensure_agent(agent_id)
            self._registry[agent_id]["error_count"] += 1

    # -------------------------------------------------
    # READ-ONLY ACCESSORS
    # -------------------------------------------------
    def get_health(self, agent_id: str) -> Dict[str, Any]:
        if not agent_id:
            raise KeyError("agent_id is required")

        with self._lock:
            self._ensure_agent(agent_id)
            return deepcopy(self._registry[agent_id])

    def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                agent_id: deepcopy(data) for agent_id, data in self._registry.items()
            }

    # -------------------------------------------------
    # INTERNAL
    # -------------------------------------------------
    def _ensure_agent(self, agent_id: str):
        if agent_id not in self._registry:
            raise KeyError(f"[AGENT_HEALTH] Agent '{agent_id}' not registered")
