# services/action_execution_service.py

"""
ACTION EXECUTION SERVICE — CANONICAL (FAZA 3.5)

Uloga:
- JEDINO mjesto gdje se WRITE stvarno IZVRŠAVA
- izvršenje ide ISKLJUČIVO preko agenata
- nema RBAC-a
- nema policy-ja
- nema approval logike
- nema UX semantike
- nema orkestracije

Sve VALIDACIJE, GOVERNANCE i APPROVAL su završeni PRIJE
(ExecutionGovernanceService + ExecutionOrchestrator)
"""

from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from services.agent_router.agent_router import AgentRouter


class ActionExecutionService:
    """
    System Write Executor (Agent-only).
    """

    STATE_COMPLETED = "COMPLETED"
    STATE_FAILED = "FAILED"

    def __init__(self):
        self.agent_router = AgentRouter()

    # ============================================================
    # PUBLIC API — EXECUTE WRITE
    # ============================================================
    async def execute(
        self,
        *,
        command: str,
        payload: Dict[str, Any],
        agent_hint: Optional[str] = None,
    ) -> Dict[str, Any]:

        execution_id = str(uuid.uuid4())
        started_at = datetime.utcnow().isoformat()
        finished_at = datetime.utcnow().isoformat()

        # --------------------------------------------------------
        # ROUTE TO AGENT
        # --------------------------------------------------------
        route = self.agent_router.route(
            {
                "command": command,
                "agent": agent_hint,
            }
        )

        agent_name = route.get("agent")
        endpoint = route.get("endpoint")

        if not endpoint:
            return {
                "execution_id": execution_id,
                "execution_state": self.STATE_FAILED,
                "reason": "No matching agent for command.",
                "agent": agent_name,
                "started_at": started_at,
                "finished_at": finished_at,
            }

        # --------------------------------------------------------
        # EXECUTE VIA AGENT
        # --------------------------------------------------------
        try:
            agent_result = await self.agent_router.execute(
                {
                    "command": command,
                    "payload": payload or {},
                }
            )
        except Exception as e:
            return {
                "execution_id": execution_id,
                "execution_state": self.STATE_FAILED,
                "reason": "Agent execution error.",
                "agent": agent_name,
                "error": str(e),
                "started_at": started_at,
                "finished_at": datetime.utcnow().isoformat(),
            }

        # --------------------------------------------------------
        # RESULT (NO SHAPING)
        # --------------------------------------------------------
        if not isinstance(agent_result, dict) or not agent_result.get("success"):
            return {
                "execution_id": execution_id,
                "execution_state": self.STATE_FAILED,
                "agent": agent_name,
                "agent_result": agent_result,
                "started_at": started_at,
                "finished_at": datetime.utcnow().isoformat(),
            }

        return {
            "execution_id": execution_id,
            "execution_state": self.STATE_COMPLETED,
            "agent": agent_name,
            "agent_result": agent_result,
            "started_at": started_at,
            "finished_at": datetime.utcnow().isoformat(),
        }
