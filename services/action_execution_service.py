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

from services.agent_router.agent_router import AgentRouter
from services.agent_router.openai_assistant_executor import (
    OpenAIAssistantExecutor,
)


class ActionExecutionService:
    """
    System Write Executor (Agent-only).
    """

    def __init__(self):
        # postojeći router ostaje (za buduće agente)
        self.agent_router = AgentRouter()

        # REALNI OpenAI agent executor
        self.openai_executor = OpenAIAssistantExecutor()

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
        """
        Izvršava WRITE akciju preko agenta.
        Ne formira execution contract.
        """

        try:
            agent_result = await self.openai_executor.execute(
                {
                    "command": command,
                    "payload": payload or {},
                }
            )
        except Exception as e:
            return {
                "success": False,
                "reason": "OpenAI agent execution error.",
                "error": str(e),
            }

        if not isinstance(agent_result, dict) or not agent_result.get("success"):
            return {
                "success": False,
                "agent_result": agent_result,
            }

        return {
            "success": True,
            "agent": agent_result.get("agent"),
            "agent_result": agent_result,
        }
