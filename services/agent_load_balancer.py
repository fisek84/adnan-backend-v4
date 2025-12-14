from typing import Dict, Any


class AgentLoadBalancer:
    """
    AgentLoadBalancer — FAZA 7 / KORAK 4

    PURPOSE:
    - Deterministička kontrola opterećenja po agentu
    - Enforcement limita po agentu (max_in_flight)

    CONSTRAINTS:
    - NEMA paralelne egzekucije bez dozvole
    - NEMA pametnog schedulinga
    - NEMA heuristike
    - NEMA autonomije
    """

    def __init__(
        self,
        *,
        max_in_flight_per_agent: int = 1,
    ):
        self._max_in_flight = max_in_flight_per_agent
        # agent_id -> in_flight_count
        self._in_flight: Dict[str, int] = {}

    # -------------------------------------------------
    # LOAD CHECK
    # -------------------------------------------------
    def can_accept(self, agent_id: str) -> bool:
        """
        Returns True if agent can accept a new task.
        """
        return self._in_flight.get(agent_id, 0) < self._max_in_flight

    # -------------------------------------------------
    # RESERVATION
    # -------------------------------------------------
    def reserve(self, agent_id: str):
        """
        Reserves one execution slot for agent.
        Must be called BEFORE execution.
        """
        current = self._in_flight.get(agent_id, 0)
        if current >= self._max_in_flight:
            raise RuntimeError(
                f"[LOAD_BALANCER] Agent '{agent_id}' exceeded max_in_flight limit"
            )

        self._in_flight[agent_id] = current + 1

    # -------------------------------------------------
    # RELEASE
    # -------------------------------------------------
    def release(self, agent_id: str):
        """
        Releases one execution slot for agent.
        Must be called AFTER execution.
        """
        current = self._in_flight.get(agent_id, 0)
        if current <= 0:
            # defensive: never go negative
            self._in_flight[agent_id] = 0
            return

        self._in_flight[agent_id] = current - 1

    # -------------------------------------------------
    # READ-ONLY SNAPSHOT
    # -------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        """
        Returns current in-flight snapshot.
        """
        return dict(self._in_flight)
