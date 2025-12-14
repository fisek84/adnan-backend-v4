from typing import Dict, Any, Optional, List


class AgentAssignmentService:
    """
    AgentAssignmentService — FAZA 7 / KORAK 3

    PURPOSE:
    - Determinističko mapiranje taska na agenta
    - Zasnovano ISKLJUČIVO na:
        - agent identity & capabilities
        - agent health status

    CONSTRAINTS:
    - NEMA execution-a
    - NEMA heuristike
    - NEMA paralelizma
    - NEMA učenja
    - SAMO pravila
    """

    def __init__(
        self,
        *,
        agents_identity: Dict[str, Dict[str, Any]],
        agent_health_registry,
    ):
        """
        agents_identity:
            Output iz load_agents_identity()
        agent_health_registry:
            Instanca AgentHealthRegistry
        """
        self._agents_identity = agents_identity
        self._health = agent_health_registry

    # -------------------------------------------------
    # ASSIGNMENT
    # -------------------------------------------------
    def assign_agent(self, command: str) -> Optional[str]:
        """
        Returns agent_id for given command, or None if no agent is eligible.
        Deterministic order: sorted agent_id.
        """
        eligible_agents: List[str] = []

        for agent_id, agent in self._agents_identity.items():
            if not agent.get("enabled", False):
                continue

            if command not in agent.get("capabilities", []):
                continue

            try:
                health = self._health.get_health(agent_id)
            except KeyError:
                # agent not registered in health registry
                continue

            if not health.get("alive", False):
                continue

            eligible_agents.append(agent_id)

        if not eligible_agents:
            return None

        # Deterministic selection
        eligible_agents.sort()
        return eligible_agents[0]
