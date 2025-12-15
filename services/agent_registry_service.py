"""
AGENT REGISTRY SERVICE — CANONICAL (FAZA 6)

Uloga:
- CENTRALNI REGISTRY svih agenata u sistemu
- jedini izvor istine za:
  - identitet
  - status
  - capabilities
  - verzije
- NEMA execution
- NEMA routing
- NEMA load balancing
- NEMA OpenAI poziva
"""

from typing import Dict, List, Optional
from datetime import datetime


class AgentRegistryService:
    def __init__(self):
        # In-memory registry (kanonski za FAZU 6)
        self._agents: Dict[str, Dict] = {}

    # =========================================================
    # REGISTRATION
    # =========================================================
    def register_agent(
        self,
        *,
        agent_name: str,
        agent_id: str,
        capabilities: List[str],
        version: str,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """
        Registruje ili ažurira agenta.
        """

        now = datetime.utcnow().isoformat()

        agent = {
            "agent_name": agent_name,
            "agent_id": agent_id,
            "capabilities": set(capabilities),
            "version": version,
            "status": "active",  # active | disabled
            "registered_at": now,
            "updated_at": now,
            "metadata": metadata or {},
        }

        self._agents[agent_name] = agent
        return agent.copy()

    # =========================================================
    # LOOKUP
    # =========================================================
    def get_agent(self, agent_name: str) -> Optional[Dict]:
        agent = self._agents.get(agent_name)
        if not agent:
            return None
        return agent.copy()

    def list_agents(self) -> List[Dict]:
        return [a.copy() for a in self._agents.values()]

    def get_agents_with_capability(self, capability: str) -> List[Dict]:
        return [
            a.copy()
            for a in self._agents.values()
            if capability in a.get("capabilities", set())
            and a.get("status") == "active"
        ]

    # =========================================================
    # STATUS MANAGEMENT
    # =========================================================
    def disable_agent(self, agent_name: str, reason: str) -> bool:
        agent = self._agents.get(agent_name)
        if not agent:
            return False

        agent["status"] = "disabled"
        agent["metadata"]["disabled_reason"] = reason
        agent["updated_at"] = datetime.utcnow().isoformat()
        return True

    def enable_agent(self, agent_name: str) -> bool:
        agent = self._agents.get(agent_name)
        if not agent:
            return False

        agent["status"] = "active"
        agent["updated_at"] = datetime.utcnow().isoformat()
        return True

    # =========================================================
    # SNAPSHOT (READ-ONLY)
    # =========================================================
    def snapshot(self) -> Dict[str, Dict]:
        return {
            name: {
                "agent_id": a["agent_id"],
                "capabilities": list(a["capabilities"]),
                "status": a["status"],
                "version": a["version"],
                "metadata": a.get("metadata", {}),
                "read_only": True,
            }
            for name, a in self._agents.items()
        }
