from typing import Dict, Any
from datetime import datetime
import threading


class AgentHealthRegistry:
    """
    AgentHealthRegistry — FAZA 7 / KORAK 2

    PURPOSE:
    - Centralni, pasivni registry zdravstvenog stanja agenata
    - Evidencija:
        - alive / down
        - last_seen
        - error_count

    CONSTRAINTS:
    - NEMA execution-a
    - NEMA restartovanja
    - NEMA failover-a
    - NEMA autonomnih odluka
    - SAMO evidencija i eksplicitni update-i
    """

    def __init__(self):
        # thread-safe jer će biti čitan iz više servisa
        self._lock = threading.Lock()

        # agent_id -> health record
        self._registry: Dict[str, Dict[str, Any]] = {}

    # -------------------------------------------------
    # REGISTRATION
    # -------------------------------------------------
    def register_agent(self, agent_id: str):
        """
        Registers agent in health registry.
        Does NOT imply agent is alive.
        """
        with self._lock:
            if agent_id not in self._registry:
                self._registry[agent_id] = {
                    "alive": False,
                    "last_seen": None,
                    "error_count": 0,
                }

    # -------------------------------------------------
    # HEARTBEAT / STATUS UPDATE
    # -------------------------------------------------
    def mark_alive(self, agent_id: str):
        """
        Marks agent as alive and updates last_seen timestamp.
        """
        with self._lock:
            self._ensure_agent(agent_id)
            self._registry[agent_id]["alive"] = True
            self._registry[agent_id]["last_seen"] = datetime.utcnow().isoformat()

    def mark_down(self, agent_id: str):
        """
        Marks agent as down.
        """
        with self._lock:
            self._ensure_agent(agent_id)
            self._registry[agent_id]["alive"] = False

    def record_error(self, agent_id: str):
        """
        Increments error counter for agent.
        """
        with self._lock:
            self._ensure_agent(agent_id)
            self._registry[agent_id]["error_count"] += 1

    # -------------------------------------------------
    # READ-ONLY ACCESSORS
    # -------------------------------------------------
    def get_health(self, agent_id: str) -> Dict[str, Any]:
        """
        Returns health snapshot for single agent.
        """
        with self._lock:
            self._ensure_agent(agent_id)
            return dict(self._registry[agent_id])

    def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns health snapshot for all agents.
        """
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
            raise KeyError(
                f"[AGENT_HEALTH] Agent '{agent_id}' not registered"
            )
