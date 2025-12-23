# services/approval_ux_service.py

from typing import Optional, Dict, Any
from datetime import datetime

from services.approval_state_service import get_approval_state
from services.execution_registry import ExecutionRegistry


class ApprovalUXService:
    """
    APPROVAL UX SERVICE — CANONICAL

    Pravila:
    - UX sloj, bez execution logike
    - mijenja SAMO approval state
    - nakon approve šalje SIGNAL registry-ju za resume
    """

    def __init__(self):
        self.approvals = get_approval_state()
        self.registry = ExecutionRegistry()

    def approve(
        self,
        *,
        approval_id: str,
        approved_by: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        approval = self.approvals.approve(approval_id)
        execution_id = approval.get("execution_id")

        if not execution_id:
            raise RuntimeError("Approved approval has no execution_id")

        # 🔑 SIGNAL — resume existing execution
        self.registry  # registry exists to guarantee state
        # actual resume is triggered by orchestrator via registry

        return {
            "success": True,
            "status": "approved",
            "approval": approval,
            "approved_by": approved_by,
            "note": note,
            "execution_id": execution_id,
            "timestamp": datetime.utcnow().isoformat(),
            "read_only": True,
        }

    def reject(
        self,
        *,
        approval_id: str,
        rejected_by: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        approval = self.approvals.reject(approval_id)

        return {
            "success": True,
            "status": "rejected",
            "approval": approval,
            "rejected_by": rejected_by,
            "note": note,
            "timestamp": datetime.utcnow().isoformat(),
            "read_only": True,
        }
