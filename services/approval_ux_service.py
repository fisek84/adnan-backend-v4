"""
APPROVAL UX SERVICE — CANONICAL (FAZA 3)

Uloga:
- JEDINI UX ulaz za approval akcije
- mapira CEO potvrdu u strogo definisan approval signal
- NE izvršava ništa
- NE donosi odluke
- NE radi governance
- NE dira execution

CEO potvrda ≠ execution
CEO potvrda = signal SYSTEMU
"""

from typing import Dict, Any
from datetime import datetime

from services.approval_state_service import ApprovalStateService


class ApprovalUXService:
    """
    UX-facing approval handler (FAZA 3).
    """

    def __init__(self):
        self._approvals = ApprovalStateService()

    # =========================================================
    # CEO APPROVAL INPUT
    # =========================================================
    def approve(
        self,
        *,
        approval_id: str,
        approved_by: str,
        note: str | None = None,
    ) -> Dict[str, Any]:
        """
        CEO eksplicitno ODOBRAVA approval.
        """

        try:
            state = self._approvals.approve(approval_id)
        except KeyError:
            return {
                "success": False,
                "error": "approval_not_found",
                "timestamp": datetime.utcnow().isoformat(),
                "read_only": True,
            }

        return {
            "success": True,
            "approval": state,
            "approved_by": approved_by,
            "note": note,
            "timestamp": datetime.utcnow().isoformat(),
            "read_only": False,
        }

    # =========================================================
    # CEO REJECTION
    # =========================================================
    def reject(
        self,
        *,
        approval_id: str,
        rejected_by: str,
        note: str | None = None,
    ) -> Dict[str, Any]:
        """
        CEO eksplicitno ODBIJA approval.
        """

        try:
            state = self._approvals.reject(approval_id)
        except KeyError:
            return {
                "success": False,
                "error": "approval_not_found",
                "timestamp": datetime.utcnow().isoformat(),
                "read_only": True,
            }

        return {
            "success": True,
            "approval": state,
            "rejected_by": rejected_by,
            "note": note,
            "timestamp": datetime.utcnow().isoformat(),
            "read_only": False,
        }
