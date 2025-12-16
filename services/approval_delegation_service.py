# services/approval_delegation_service.py

from typing import Dict, Any
from models.ai_command import AICommand

from services.approval_state_service import ApprovalStateService
from services.execution_orchestrator import ExecutionOrchestrator


class ApprovalDelegationService:
    """
    APPROVAL → DELEGATION MATERIALIZER (FAZA 9)

    Uloga:
    - materijalizuje VEĆ ODOBRENU approval u AICommand
    - NE donosi odluke
    - NE radi UX
    - NE zaobilazi governance
    - deterministički i audit-safe
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

        if not approval_id or not executor:
            return {
                "success": False,
                "reason": "invalid_delegation_request",
            }

        approval = self._approvals.get(approval_id)

        if approval.get("status") != "approved":
            return {
                "success": False,
                "reason": "approval_not_approved",
            }

        # payload_summary JE jedini izvor istine
        payload_summary = approval.get("payload_summary") or {}

        command_name = payload_summary.get("command")
        payload = payload_summary.get("payload") or {}

        if not isinstance(command_name, str) or not command_name:
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

        # Hint ko izvršava (agent / system worker)
        ai_command.executor = executor

        return await self._orchestrator.execute(ai_command)
