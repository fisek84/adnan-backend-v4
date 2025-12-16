# services/approval_ux_service.py

"""
APPROVAL UX SERVICE — CANONICAL

Uloga:
- UX layer za approval
- NE drži state
- NE kreira state
- koristi ISKLJUČIVO canonical ApprovalStateService singleton
"""

from typing import Optional, Dict, Any
from datetime import datetime

from services.approval_state_service import get_approval_state


class ApprovalUXService:
    def __init__(self):
        # ✅ CANONICAL SHARED STATE
        self.approvals = get_approval_state()

    def approve(
        self,
        *,
        approval_id: str,
        approved_by: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:

        approval = self.approvals.approve(approval_id)

        return {
            "success": True,
            "status": "approved",
            "approval": approval,
            "approved_by": approved_by,
            "note": note,
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
