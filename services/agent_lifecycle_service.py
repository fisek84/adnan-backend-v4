from typing import Dict
import threading


class AgentLifecycleService:
    """
    AgentLifecycleService — FAZA 7 / KORAK 6 (FINAL)

    PURPOSE:
    - Eksplicitna deaktivacija i reaktivacija agenata
    - Policy / manual driven
    - Centralni lifecycle kontrolni sloj

    CONSTRAINTS:
    - NEMA autonomnog povratka
    - NEMA eskalacije
    - NEMA execution-a
    - SAMO eksplicitne operacije
    """

    def __init__(self):
        self._lock = threading.Lock()
        # agent_id -> active (bool)
        self._agent_active: Dict[str, bool] = {}

    # -------------------------------------------------
    # LIFECYCLE CONTROL
    # -------------------------------------------------
    def deactivate(self, agent_id: str):
        """
        Deactivates agent explicitly.
        Deactivated agent MUST NOT receive new assignments.
        """
        with self._lock:
            self._agent_active[agent_id] = False

    def reactivate(self, agent_id: str):
        """
        Reactivates agent explicitly.
        Reactivation is manual or policy-driven only.
        """
        with self._lock:
            self._agent_active[agent_id] = True

    # -------------------------------------------------
    # STATUS
    # -------------------------------------------------
    def is_active(self, agent_id: str) -> bool:
        """
        Returns True if agent is active.
        Default is True unless explicitly deactivated.
        """
        with self._lock:
            return self._agent_active.get(agent_id, True)

    # -------------------------------------------------
    # SNAPSHOT
    # -------------------------------------------------
    def snapshot(self) -> Dict[str, bool]:
        """
        Returns snapshot of agent lifecycle states.
        """
        with self._lock:
            return dict(self._agent_active)
