from typing import Dict, Any
from datetime import datetime
import threading


class AgentHealthRegistry:
    """
    AgentHealthRegistry — FAZA 7 / KORAK 2

    Canonical fix:
    - Agents declared in identity are considered "available" at boot.
    - Health registry still tracks last_seen / error_count.
    - No execution, no restart logic.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._registry: Dict[str, Dict[str, Any]] = {}

    # -------------------------------------------------
    # REGISTRATION
    # -------------------------------------------------
    def register_agent(self, agent_id: str, *, alive: bool = True):
        """
        Registers agent in health registry.

        Canonical rule:
        - identity-defined agents are treated as alive at startup
          (availability is then controlled by lifecycle/isolation/load/governance).
        """
        with self._lock:
            if agent_id not in self._registry:
                self._registry[agent_id] = {
                    "alive": bool(alive),
                    "last_seen": datetime.utcnow().isoformat() if alive else None,
                    "error_count": 0,
                }
            else:
                self._registry[agent_id]["alive"] = bool(alive)
                if alive:
                    self._registry[agent_id]["last_seen"] = datetime.utcnow().isoformat()

    # -------------------------------------------------
    # HEARTBEAT / STATUS UPDATE
    # -------------------------------------------------
    def mark_alive(self, agent_id: str):
        with self._lock:
            self._ensure_agent(agent_id)
            self._registry[agent_id]["alive"] = True
            self._registry[agent_id]["last_seen"] = datetime.utcnow().isoformat()

    def mark_down(self, agent_id: str):
        with self._lock:
            self._ensure_agent(agent_id)
            self._registry[agent_id]["alive"] = False

    def record_error(self, agent_id: str):
        with self._lock:
            self._ensure_agent(agent_id)
            self._registry[agent_id]["error_count"] += 1

    # -------------------------------------------------
    # READ-ONLY ACCESSORS
    # -------------------------------------------------
    def get_health(self, agent_id: str) -> Dict[str, Any]:
        with self._lock:
            self._ensure_agent(agent_id)
            return dict(self._registry[agent_id])

    def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                agent_id: dict(data)
                for agent_id, data in self._registry.items()
            }

    # -------------------------------------------------
    # INTERNAL
    # -------------------------------------------------
    def _ensure_agent(self, agent_id: str):
        if agent_id not in self._registry:
            raise KeyError(f"[AGENT_HEALTH] Agent '{agent_id}' not registered")
 