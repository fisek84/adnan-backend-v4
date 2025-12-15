from typing import Dict, Any
from models.ai_command import AICommand

from services.approval_state_service import ApprovalStateService
from services.execution_orchestrator import ExecutionOrchestrator


class ApprovalDelegationService:
    """
    APPROVAL → DELEGATION MATERIALIZER (FAZA 4)

    Uloga:
    - pretvara APPROVED approval u konkretan AICommand
    - NE donosi odluke
    - NE radi UX
    - NE zaobilazi governance
    """

    def __init__(self):
        self._approvals = ApprovalStateService()
        self._orchestrator = ExecutionOrchestrator()

    async def delegate(
        self,
        *,
        approval_id: str,
        executor: str,
    ) -> Dict[str, Any]:

        approval = self._approvals.get(approval_id)

        if approval.get("status") != "approved":
            return {
                "success": False,
                "reason": "approval_not_approved",
            }

        # payload_summary JE izvor istine
        payload_summary = approval.get("payload_summary", {})

        command_name = payload_summary.get("command")
        payload = payload_summary.get("payload", {})

        if not command_name:
            return {
                "success": False,
                "reason": "missing_command_in_approval",
            }

        ai_command = AICommand(
            command=command_name,
            intent="delegated_execution",
            input=payload,
            params={},
            metadata={
                "context_type": "system",
                "approval_id": approval_id,
            },
            validated=True,
        )

        # Hint ko izvršava (agent)
        ai_command.executor = executor

        return await self._orchestrator.execute(ai_command)
