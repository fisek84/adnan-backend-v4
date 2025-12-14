from typing import Dict, Set
import threading


class AgentIsolationService:
    """
    AgentIsolationService — FAZA 7 / KORAK 5

    PURPOSE:
    - Eksplicitna izolacija agenata
    - Blokiranje daljeg rada izolovanog agenta

    CONSTRAINTS:
    - NEMA self-healinga
    - NEMA autonomnih odluka
    - NEMA execution-a
    - SAMO eksplicitna kontrola
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._isolated_agents: Set[str] = set()

    # -------------------------------------------------
    # ISOLATION CONTROL
    # -------------------------------------------------
    def isolate(self, agent_id: str):
        """
        Isolates agent explicitly.
        """
        with self._lock:
            self._isolated_agents.add(agent_id)

    def release(self, agent_id: str):
        """
        Releases agent from isolation explicitly.
        """
        with self._lock:
            self._isolated_agents.discard(agent_id)

    # -------------------------------------------------
    # CHECK
    # -------------------------------------------------
    def is_isolated(self, agent_id: str) -> bool:
        """
        Returns True if agent is currently isolated.
        """
        with self._lock:
            return agent_id in self._isolated_agents

    # -------------------------------------------------
    # SNAPSHOT
    # -------------------------------------------------
    def snapshot(self) -> Dict[str, bool]:
        """
        Returns snapshot of isolated agents.
        """
        with self._lock:
            return {agent_id: True for agent_id in self._isolated_agents}
