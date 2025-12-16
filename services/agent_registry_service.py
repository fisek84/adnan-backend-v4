# services/agent_registry_service.py

"""
AGENT REGISTRY SERVICE — CANONICAL (FAZA 10)

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
- READ-ONLY iz perspektive executiona
"""

from typing import Dict, List, Optional
from datetime import datetime
from threading import Lock
from copy import deepcopy


class AgentRegistryService:
    def __init__(self):
        # In-memory registry (kanonski za FAZU 10)
        self._agents: Dict[str, Dict] = {}
        self._lock = Lock()

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

        if not agent_name or not agent_id:
            raise ValueError("agent_name and agent_id are required")

        if not isinstance(capabilities, list):
            raise ValueError("capabilities must be a list")

        now = datetime.utcnow().isoformat()

        agent = {
            "agent_name": agent_name,
            "agent_id": agent_id,
            "capabilities": set(capabilities),
            "version": version,
            "status": "active",  # active | disabled
            "registered_at": self._agents.get(agent_name, {}).get("registered_at", now),
            "updated_at": now,
            "metadata": metadata or {},
        }

        with self._lock:
            self._agents[agent_name] = agent

        return deepcopy(agent)

    # =========================================================
    # LOOKUP
    # =========================================================
    def get_agent(self, agent_name: str) -> Optional[Dict]:
        if not agent_name:
            return None
        with self._lock:
            agent = self._agents.get(agent_name)
            return deepcopy(agent) if agent else None

    def list_agents(self) -> List[Dict]:
        with self._lock:
            return [deepcopy(a) for a in self._agents.values()]

    def get_agents_with_capability(self, capability: str) -> List[Dict]:
        if not capability:
            return []

        with self._lock:
            return [
                deepcopy(a)
                for a in self._agents.values()
                if capability in a.get("capabilities", set())
                and a.get("status") == "active"
            ]

    # =========================================================
    # STATUS MANAGEMENT
    # =========================================================
    def disable_agent(self, agent_name: str, reason: str) -> bool:
        if not agent_name:
            return False

        with self._lock:
            agent = self._agents.get(agent_name)
            if not agent:
                return False

            agent["status"] = "disabled"
            agent.setdefault("metadata", {})["disabled_reason"] = reason
            agent["updated_at"] = datetime.utcnow().isoformat()
            return True

    def enable_agent(self, agent_name: str) -> bool:
        if not agent_name:
            return False

        with self._lock:
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
        with self._lock:
            return {
                name: {
                    "agent_id": a["agent_id"],
                    "capabilities": list(a["capabilities"]),
                    "status": a["status"],
                    "version": a["version"],
                    "metadata": deepcopy(a.get("metadata", {})),
                    "read_only": True,
                }
                for name, a in self._agents.items()
            }
