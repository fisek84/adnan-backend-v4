from typing import Dict, Any, Optional, List


class AgentAssignmentService:
    """
    AgentAssignmentService — FAZA 7 / KORAK 3 (FIXED)

    PURPOSE:
    - Determinističko mapiranje EXECUTORA na agenta
    - Zasnovano ISKLJUČIVO na:
        - agent identity
        - enabled flag
        - agent health status

    COMMAND → EXECUTOR mapiranje je VEĆ odrađeno ranije
    """

    def __init__(
        self,
        *,
        agents_identity: Dict[str, Dict[str, Any]],
        agent_health_registry,
    ):
        self._agents_identity = agents_identity
        self._health = agent_health_registry

    # -------------------------------------------------
    # ASSIGNMENT
    # -------------------------------------------------
    def assign_agent(self, executor: str) -> Optional[str]:
        """
        Returns agent_id for given executor, or None if no agent is eligible.
        Deterministic order: sorted agent_id.
        """

        eligible_agents: List[str] = []

        for agent_id, agent in self._agents_identity.items():
            # enabled check
            if not agent.get("enabled", False):
                continue

            # executor match (KEY FIX)
            if agent_id != executor:
                continue

            try:
                health = self._health.get_health(agent_id)
            except KeyError:
                continue

            if not health.get("alive", False):
                continue

            eligible_agents.append(agent_id)

        if not eligible_agents:
            return None

        eligible_agents.sort()
        return eligible_agents[0]
