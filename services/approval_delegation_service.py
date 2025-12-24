# services/approval_delegation_service.py

from __future__ import annotations

from typing import Any, Dict

from models.ai_command import AICommand
from services.approval_state_service import ApprovalStateService, get_approval_state
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

    def __init__(
        self,
        approvals: ApprovalStateService | None = None,
        orchestrator: ExecutionOrchestrator | None = None,
    ):
        # koristi canonical singleton po defaultu (shared store)
        self._approvals: ApprovalStateService = approvals or get_approval_state()
        self._orchestrator: ExecutionOrchestrator = (
            orchestrator or ExecutionOrchestrator()
        )

    async def delegate(
        self,
        *,
        approval_id: str,
        executor: str,
    ) -> Dict[str, Any]:
        if not approval_id or not isinstance(approval_id, str):
            return {
                "success": False,
                "reason": "invalid_delegation_request",
            }

        if not executor or not isinstance(executor, str):
            return {
                "success": False,
                "reason": "invalid_delegation_request",
            }

        try:
            approval = self._approvals.get(approval_id)
        except KeyError:
            return {
                "success": False,
                "reason": "approval_not_found",
            }

        if approval.get("status") != "approved":
            return {
                "success": False,
                "reason": "approval_not_approved",
            }

        # payload_summary JE jedini izvor istine
        payload_summary_raw = approval.get("payload_summary") or {}
        payload_summary: Dict[str, Any] = (
            payload_summary_raw if isinstance(payload_summary_raw, dict) else {}
        )

        command_name = payload_summary.get("command")
        payload_raw = payload_summary.get("payload") or {}
        payload: Dict[str, Any] = payload_raw if isinstance(payload_raw, dict) else {}

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
                "executor": executor,
            },
            validated=True,
        )

        # Hint ko izvršava (agent / system worker)
        # (ne ruši runtime ako model nema field)
        try:
            setattr(ai_command, "executor", executor)
        except Exception:
            pass

        return await self._orchestrator.execute(ai_command)
